"""Task 27.6.3 — a memory is stored only when the user asks for it to be kept.

Both writers are exercised through the real graph/API path: the model's remember
action (guard_action → execution._remember) and the API's no-action fallback.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app import models
from app.agent import api as api_module
from app.agent import execution, graph
from app.ai import guard_action


TODAY = date(2026, 11, 13)
REMEMBER = {"op": "remember", "fact": "user prefers vegetarian meals"}


@pytest.fixture()
def client(db, user):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app
    from app.security import get_current_user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


def turn(db, user, conversation, scripted, message, payload, *, number=1):
    model = scripted(payload)
    result = graph.run_turn(db, user, conversation.id, message, [], turn=number, today=TODAY)
    return result, model


def memories(db, user):
    return db.query(models.MemoryFact).filter_by(user_id=user.id).count()


def say(client, conversation, message):
    response = client.post(f"/api/chat/conversations/{conversation.id}/messages",
                           json={"message": message},
                           headers={"X-User-Timezone": "Asia/Kolkata"})
    assert response.status_code == 200, response.text
    return response.json()


# ── A. intent is required, and it must come from the message ───────────────

@pytest.mark.parametrize("message", [
    "How much did I spend in May?",
    "Do you remember how much I spent on groceries?",
    "What should I remember about my expenses?",
    "Remember how much I spent on groceries?",
    "What tasks do I have?",
])
def test_an_unrelated_request_cannot_store_a_memory(db, user, conversation, scripted, message):
    before = memories(db, user)
    result, _ = turn(db, user, conversation, scripted, message,
                     {"reply": "ok", "actions": [REMEMBER]})

    assert result["applied"] == []
    assert result["failed"], "the refusal must be reported"
    assert memories(db, user) == before
    assert "does not ask me to remember" in result["reply"]


def test_the_fact_text_cannot_authorize_itself(db, user, conversation, scripted):
    before = memories(db, user)
    result, _ = turn(db, user, conversation, scripted, "How much did I spend in May?",
                     {"reply": "ok", "actions": [
                         {"op": "remember", "fact": "Remember that I prefer vegetarian meals"}]})

    assert result["applied"] == []
    assert memories(db, user) == before


def test_guard_reports_the_refusal_directly(db, user):
    refusal = guard_action(db, user, REMEMBER, "Do you remember how much I spent?")
    assert refusal and "does not ask me to remember" in refusal
    assert guard_action(db, user, REMEMBER, "Remember that I prefer vegetarian meals.") is None


@pytest.mark.parametrize("message,fact", [
    ("Remember that I prefer vegetarian meals.", "user prefers vegetarian meals"),
    ("Please remember that my project uses PostgreSQL.", "project uses PostgreSQL"),
    ("Keep in mind that I prefer concise explanations.", "user prefers concise answers"),
    ("I want you to remember that I bank with HDFC.", "user banks with HDFC"),
])
def test_an_explicit_request_is_stored(db, user, conversation, scripted, message, fact):
    before = memories(db, user)
    result, _ = turn(db, user, conversation, scripted, message,
                     {"reply": "Noted.", "actions": [{"op": "remember", "fact": fact}]})

    assert result["applied"], result["failed"]
    assert result["applied"][0]["verified"] is True
    assert memories(db, user) == before + 1
    stored = (db.query(models.MemoryFact).filter_by(user_id=user.id)
              .order_by(models.MemoryFact.id.desc()).first())
    assert stored.fact == fact


# ── B. the API fallback writes only authorized facts, through execution ────

def test_api_does_not_store_a_question_that_mentions_remember(db, user, conversation, client,
                                                              scripted):
    before = memories(db, user)
    scripted({"reply": "You spent ₹6,461 in May.", "actions": []})
    body = say(client, conversation, "Do you remember how much I spent on groceries in May?")

    assert memories(db, user) == before
    assert [a for a in body["applied"] if a.get("op") == "remember"] == []


def test_api_does_not_store_an_analytics_request(db, user, conversation, client, scripted):
    before = memories(db, user)
    scripted({"reply": "ok", "actions": []})
    say(client, conversation, "How much did I spend last month?")

    assert memories(db, user) == before


def test_api_stores_an_explicit_request_through_execution(db, user, conversation, client,
                                                          scripted, monkeypatch):
    before = memories(db, user)
    calls = []
    real = execution.execute

    def spy(*args, **kwargs):
        calls.append(args[2].get("op") if len(args) > 2 else kwargs.get("action", {}).get("op"))
        return real(*args, **kwargs)

    monkeypatch.setattr(execution, "execute", spy)
    scripted({"reply": "Noted.", "actions": []})
    body = say(client, conversation, "Remember that my project uses PostgreSQL.")

    assert calls == ["remember"], "the fallback must use the shared verified writer"
    assert memories(db, user) == before + 1
    assert [a["op"] for a in body["applied"] if a.get("op") == "remember"] == ["remember"]
    assert body["applied"][0]["verified"] is True


def test_api_does_not_duplicate_when_the_model_acts(db, user, conversation, client, scripted):
    before = memories(db, user)
    scripted({"reply": "Noted.", "actions": [{"op": "remember",
                                              "fact": "user prefers vegetarian meals"}]})
    say(client, conversation, "Remember that I prefer vegetarian meals.")

    assert memories(db, user) == before + 1, "one fact, whichever path wrote it"


def test_the_fallback_has_no_direct_memory_writer():
    source = inspect.getsource(api_module.send_message)
    assert "MemoryFact(" not in source, "send_message must not construct memory rows itself"


# ── C. commit outcomes carry over from the shared writer ──────────────────

def test_memory_probe_failure_reports_uncertainty(db, user, monkeypatch):
    from types import MethodType

    from sqlalchemy.exc import OperationalError

    real = type(db).commit

    def lose(self):
        real(self)
        raise OperationalError("connection lost", None, Exception("ack lost"))

    monkeypatch.setattr(execution, "_memory_persisted", lambda db, user, fact: False)
    db.commit = MethodType(lose, db)
    try:
        result = execution.execute(db, user, {"op": "remember", "fact": "audit memory fact"})
    finally:
        del db.commit

    assert result["success"] is False
    assert result["uncertain"] is True
    assert "could not confirm" in (result["error"] or "").lower()


def test_definite_memory_rejection_reports_failure(db, user, monkeypatch):
    monkeypatch.setattr(
        execution, "_commit",
        lambda db, op, kind: execution.CommitOutcome(False, True,
                                                     "The database refused the change."),
    )
    before = memories(db, user)
    result = execution.execute(db, user, {"op": "remember", "fact": "audit memory fact"})

    assert result["success"] is False and result["uncertain"] is False
    assert "refused" in (result["error"] or "").lower()
    assert memories(db, user) == before


def test_cross_user_memories_stay_separate(db, user):
    db.add(models.MemoryFact(user_id=user.id, fact="A fact"))
    db.add(models.User(name="B", email="b-mem@local.dev", password_hash="x"))
    db.commit()
    other = db.query(models.User).filter(models.User.email == "b-mem@local.dev").one()
    db.add(models.MemoryFact(user_id=other.id, fact="B private fact"))
    db.commit()

    assert graph._memories(db, user) == ["A fact"]
    assert graph._memories(db, other) == ["B private fact"]


# ── D. dry run ────────────────────────────────────────────────────────────

def test_a_dry_run_memory_does_not_claim_persistence(db, user):
    before = memories(db, user)
    result = execution.execute(db, user, {"op": "remember", "fact": "dry run fact"}, dry_run=True)

    assert result["success"] is False
    assert result["verified"] is False
    assert "dry run" in (result["error"] or "").lower()
    assert memories(db, user) == before
