"""Task 27.6.2 — a failed graph turn never replays a committed write.

Every test injects a failure at a named stage and then checks the database and
the provider's call count. A recovery that quietly ran `act` again would show up
as two rows and two model calls.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import graph, providers


TODAY = date(2026, 11, 13)


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


def tasks(db, user):
    return db.query(models.Task).filter(models.Task.user_id == user.id)


def txns(db, user):
    return db.query(models.Transaction).filter(models.Transaction.user_id == user.id)


TASK_ACTION = {"op": "add_task", "text": "Pay audit rent", "due": "2026-11-20"}
TXN_ACTION = {"op": "add_transaction", "kind": "expense", "amount": 500,
              "category": "Groceries", "payment_method": "UPI", "txn_date": "2026-11-13"}


# ── A. the normal path still runs each action once ─────────────────────────

def test_normal_task_creation_runs_once(db, user, conversation, scripted):
    before = tasks(db, user).count()
    result, model = turn(db, user, conversation, scripted, "Create a task to pay audit rent",
                         {"reply": "Added.", "actions": [TASK_ACTION]})

    assert len(model.calls) == 1
    assert result["graph_error"] == ""
    assert not result.get("uncertain") and not result.get("partial")
    assert [a["operation"] for a in result["applied"]] == ["add_task"]
    assert tasks(db, user).count() == before + 1


def test_normal_transaction_creation_runs_once(db, user, conversation, scripted):
    before = txns(db, user).count()
    result, model = turn(db, user, conversation, scripted, "I spent 500 on groceries today",
                         {"reply": "Recorded.", "actions": [TXN_ACTION]})

    assert len(model.calls) == 1
    assert result["graph_error"] == ""
    assert txns(db, user).count() == before + 1


# ── B. the failure that produced the duplicate ─────────────────────────────

def test_finish_failure_after_a_committed_task_does_not_replay(db, user, conversation, scripted,
                                                               monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    before = tasks(db, user).count()
    result, model = turn(db, user, conversation, scripted, "Create a task to pay audit rent",
                         {"reply": "Added.", "actions": [TASK_ACTION]})

    assert len(model.calls) == 1, "the model must not be asked again"
    assert tasks(db, user).count() == before + 1, "exactly one row, not two"
    assert result["runner"] == "recovered"
    assert "RuntimeError" in result["graph_error"]
    assert len(result["applied"]) == 1 and result["applied"][0]["verified"] is True
    assert result["reply"].startswith("Done —")


def test_response_formatting_failure_does_not_replay(db, user, conversation, scripted,
                                                     monkeypatch):
    monkeypatch.setattr(graph, "clean_reply",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("clean broke")))
    before = txns(db, user).count()
    result, model = turn(db, user, conversation, scripted, "I spent 500 on groceries today",
                         {"reply": "Recorded.", "actions": [TXN_ACTION]})

    assert len(model.calls) == 1
    assert txns(db, user).count() == before + 1
    assert result["graph_error"], "the failure must be reported"
    assert result["uncertain"] is False, "the write reported its own result"


# ── C. failures before any write ───────────────────────────────────────────

def test_failure_before_act_writes_nothing(db, user, conversation, scripted, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("model crashed")

    monkeypatch.setattr(providers, "ask", boom)
    before_tasks, before_txns = tasks(db, user).count(), txns(db, user).count()
    result = graph.run_turn(db, user, conversation.id, "Create a task to pay audit rent", [],
                            turn=1, today=TODAY)

    assert tasks(db, user).count() == before_tasks
    assert txns(db, user).count() == before_txns
    assert result["applied"] == [] and result["pending"] == []
    assert "RuntimeError" in result["graph_error"]
    assert "nothing was saved" in result["reply"].lower()


def test_failure_in_recall_writes_nothing(db, user, conversation, scripted, monkeypatch):
    monkeypatch.setattr(graph, "build_snapshot",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("snapshot broke")))
    before = tasks(db, user).count()
    result, model = turn(db, user, conversation, scripted, "Create a task to pay audit rent",
                         {"reply": "Added.", "actions": [TASK_ACTION]})

    assert len(model.calls) == 0, "no action can exist without a model call"
    assert tasks(db, user).count() == before
    assert "RuntimeError" in result["graph_error"]


def test_read_only_stage_failure_keeps_the_answer(db, user, conversation, scripted, monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    before = txns(db, user).count()
    result, model = turn(db, user, conversation, scripted, "How much did I spend in May?",
                         {"reply": "You spent ₹36,078.77 in May.", "actions": []})

    assert txns(db, user).count() == before
    assert result["applied"] == []
    assert "₹36,078.77" in result["reply"], "an analytics answer survives a formatting failure"
    assert "RuntimeError" in result["graph_error"]


# ── D. an unknown outcome is reported, never retried ───────────────────────

def test_unknown_commit_outcome_is_not_retried(db, user, conversation, scripted, monkeypatch):
    real = graph.execution.execute

    def commit_then_die(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("connection lost after commit")

    monkeypatch.setattr(graph.execution, "execute", commit_then_die)
    before = tasks(db, user).count()
    result, model = turn(db, user, conversation, scripted, "Create a task to pay audit rent",
                         {"reply": "Added.", "actions": [TASK_ACTION]})

    assert len(model.calls) == 1
    assert tasks(db, user).count() == before + 1, "the committed row exists — and only one"
    assert result["uncertain"] is True
    assert result["applied"] == [], "an unconfirmed outcome is not reported as applied"
    assert "could not confirm" in result["reply"].lower()
    assert "nothing was saved" not in result["reply"].lower()


# ── E. pending deletions and the approval boundary ─────────────────────────

def test_pending_deletion_is_not_executed_by_recovery(db, user, conversation, scripted,
                                                     monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    result, model = turn(db, user, conversation, scripted, "Delete the task Wheel Balancing",
                         {"reply": "Deleting.", "actions": [
                             {"op": "delete_task", "text": "Wheel Balancing"}]})

    assert len(model.calls) == 1
    assert [p["operation"] for p in result["pending"]] == ["delete_task"]
    assert result["applied"] == []
    assert "confirm below" in result["reply"].lower()
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Wheel Balancing").count() == 1


def test_approval_boundary_survives_a_failed_turn(db, user, conversation, scripted,
                                                  monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    result, _ = turn(db, user, conversation, scripted, "Delete the task Wheel Balancing",
                     {"reply": "Deleting.", "actions": [
                         {"op": "delete_task", "text": "Wheel Balancing"}]})
    monkeypatch.undo()

    from app.agent import execution
    pending = result["pending"][0]
    confirmed = execution.execute(db, user, {"op": "delete_task", "id": pending["entity_id"]},
                                  context={"today": TODAY})
    assert confirmed["success"] and confirmed["verified"] is True
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Wheel Balancing").count() == 0


# ── F. authorization and analytics are unaffected ─────────────────────────

def test_creation_authorization_still_enforced_on_a_failing_turn(db, user, conversation,
                                                                 scripted, monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    before = txns(db, user).count()
    result, _ = turn(db, user, conversation, scripted, "How much did I spend in May?",
                     {"reply": "Adding.", "actions": [TXN_ACTION]})

    assert txns(db, user).count() == before
    assert result["applied"] == []
    assert "does not ask me to add" in result["reply"]


def test_the_api_reports_partial_success(db, user, conversation, client, scripted, monkeypatch):
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    scripted({"reply": "Added.", "actions": [TASK_ACTION]})
    response = client.post(f"/api/chat/conversations/{conversation.id}/messages",
                           json={"message": "Create a task to pay audit rent"},
                           headers={"X-User-Timezone": "Asia/Kolkata"})
    assert response.status_code == 200
    body = response.json()
    assert body["applied"], "the committed change is still reported"
    assert body["graph_error"], "the failure is reported without a stack trace"
    assert "Traceback" not in body["graph_error"] and "sqlalchemy" not in body["graph_error"].lower()
    assert body["partial"] is True and body["uncertain"] is False

    row = (db.query(models.ChatMessage)
           .filter(models.ChatMessage.conversation_id == conversation.id,
                   models.ChatMessage.role == "assistant")
           .order_by(models.ChatMessage.id.desc()).first())
    import json as _json
    meta = _json.loads(row.meta)
    assert meta["graph_error"] and meta["partial"] is True


def test_the_sequential_runner_never_replays_either(db, user, conversation, scripted,
                                                   monkeypatch):
    """LangGraph is optional; the fallback runner must have the same guarantee."""
    monkeypatch.setattr(graph, "LANGGRAPH_AVAILABLE", False)
    monkeypatch.setattr(graph, "normalize_currency",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish broke")))
    before = tasks(db, user).count()
    result, model = turn(db, user, conversation, scripted, "Create a task to pay audit rent",
                         {"reply": "Added.", "actions": [TASK_ACTION]})

    assert len(model.calls) == 1
    assert tasks(db, user).count() == before + 1
    assert result["runner"] == "recovered"
    assert "RuntimeError" in result["graph_error"]
