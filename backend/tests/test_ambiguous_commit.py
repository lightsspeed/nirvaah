"""Task 27.6.2.1 — a commit whose acknowledgement was lost is neither success nor failure.

The simulations below wrap the session's ``commit()`` at the Python/driver
boundary: "committed then raised" stands in for PostgreSQL committing while the
client loses the acknowledgement, and "raised before committing" stands in for a
connection that died first. Both replay the same code path a real
``OperationalError`` would take, but they are **not** real PostgreSQL network
faults — only a fault injector or ``pg_terminate_backend`` proves that.
"""

from __future__ import annotations

from datetime import date
from types import MethodType

import pytest
from sqlalchemy.exc import OperationalError

from app import models
from app.agent import execution, graph


TODAY = date(2026, 11, 13)
SEEDED_TASK_ID = "seed-wheel-balancing"


def lose_ack(db, *, after_commit=True, times=1, only_task_text=None):
    """Wrap commit(): commit (or not), then raise as a dropped connection would.

    ``only_task_text`` narrows the fault to the commit that carries that task, so
    an API-level test does not break the user-message insert that precedes it.
    """
    real = type(db).commit
    state = {"calls": 0}

    def commit(self):
        state["calls"] += 1
        trigger = True
        if only_task_text is not None:
            trigger = any(isinstance(obj, models.Task) and getattr(obj, "text", None) == only_task_text
                          for obj in self.new)
        if (only_task_text is not None and trigger) or (only_task_text is None and state["calls"] <= times):
            if after_commit:
                real(self)
            raise OperationalError("server closed the connection unexpectedly", None,
                                   Exception("acknowledgement lost"))
        real(self)

    db.commit = MethodType(commit, db)
    return state


def restore(db):
    del db.commit


def turn(db, user, conversation, scripted, message, payload, *, number=1):
    model = scripted(payload)
    result = graph.run_turn(db, user, conversation.id, message, [], turn=number, today=TODAY)
    return result, model


def counts(db, user):
    return {
        "tasks": db.query(models.Task).filter_by(user_id=user.id).count(),
        "transactions": db.query(models.Transaction).filter_by(user_id=user.id).count(),
        "memories": db.query(models.MemoryFact).filter_by(user_id=user.id).count(),
    }


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


# ── A. the database answered and rejected the transaction ──────────────────

def test_definite_rejection_is_a_clean_failure(db, user, conversation, scripted):
    before = counts(db, user)["tasks"]
    result, model = turn(db, user, conversation, scripted,
                         "Create a task Duplicate id with id seed-wheel-balancing",
                         {"reply": "Added.", "actions": [
                             {"op": "add_task", "id": SEEDED_TASK_ID, "text": "Duplicate"}]})

    assert len(model.calls) == 1
    assert result["applied"] == []
    assert result["failed"][0]["uncertain"] is False
    assert "nothing was saved" in result["failed"][0]["error"].lower()
    assert counts(db, user)["tasks"] == before
    original = db.get(models.Task, SEEDED_TASK_ID)
    assert original is not None and original.text == "Wheel Balancing"


# ── B. the commit landed, the acknowledgement did not ─────────────────────

def test_create_confirmed_after_lost_ack(db, user, conversation, scripted):
    before = counts(db, user)["tasks"]
    lose_ack(db)
    try:
        result, model = turn(db, user, conversation, scripted, "Create a task Pay audit rent",
                             {"reply": "Added.", "actions": [
                                 {"op": "add_task", "text": "Pay audit rent"}]})
    finally:
        restore(db)

    assert len(model.calls) == 1
    assert [a["operation"] for a in result["applied"]] == ["add_task"]
    assert result["applied"][0]["verified"] is True
    assert counts(db, user)["tasks"] == before + 1, "one row, despite the lost acknowledgement"
    assert "nothing was saved" not in result["reply"].lower()
    assert result["failed"] == []


def test_update_confirmed_after_lost_ack(db, user, conversation, scripted):
    lose_ack(db)
    try:
        result, _ = turn(db, user, conversation, scripted,
                         "change priority of seed-wheel-balancing to high",
                         {"reply": "Updated.", "actions": [
                             {"op": "update_task", "id": SEEDED_TASK_ID, "priority": "high"}]})
    finally:
        restore(db)

    assert [a["operation"] for a in result["applied"]] == ["update_task"]
    assert result["applied"][0]["verified"] is True
    db.expire_all()
    assert db.get(models.Task, SEEDED_TASK_ID).priority == "high"
    assert "nothing was saved" not in result["reply"].lower()


def test_delete_confirmed_after_lost_ack(db, user):
    task = models.Task(id="audit-delete-me", user_id=user.id, text="Delete me")
    db.add(task)
    db.commit()

    lose_ack(db)
    try:
        result = execution.execute(db, user, {"op": "delete_task", "id": "audit-delete-me"},
                                   context={"today": TODAY})
    finally:
        restore(db)

    assert result["success"] is True and result["verified"] is True
    assert result["uncertain"] is False
    db.expire_all()
    assert db.get(models.Task, "audit-delete-me") is None


def test_memory_write_confirmed_after_lost_ack(db, user):
    before = counts(db, user)["memories"]
    lose_ack(db)
    try:
        result = execution.execute(db, user, {"op": "remember", "fact": "audit fact one"})
    finally:
        restore(db)

    assert result["success"] is True and result["verified"] is True
    assert counts(db, user)["memories"] == before + 1


# ── C. nothing proved either way ──────────────────────────────────────────

def test_missing_row_after_ambiguous_create_is_uncertain(db, user, conversation, scripted):
    before = counts(db, user)["tasks"]
    lose_ack(db, after_commit=False)      # the write never reached the database
    try:
        result, _ = turn(db, user, conversation, scripted, "Create a task Pay audit rent",
                         {"reply": "Added.", "actions": [{"op": "add_task", "text": "Pay audit rent"}]})
    finally:
        restore(db)

    assert counts(db, user)["tasks"] == before
    assert result["applied"] == []
    assert result["failed"][0]["uncertain"] is True
    assert "could not confirm" in result["reply"].lower()
    assert "nothing was saved" not in result["reply"].lower(), (
        "an absent row after a failed probe is not proof of rollback")


def test_failed_probe_is_uncertain(db, user, conversation, scripted, monkeypatch):
    monkeypatch.setattr(execution, "_probe_row", lambda db, model, pk: (None, False))
    lose_ack(db, after_commit=False)
    try:
        result, _ = turn(db, user, conversation, scripted, "Create a task Pay audit rent",
                         {"reply": "Added.", "actions": [{"op": "add_task", "text": "Pay audit rent"}]})
    finally:
        restore(db)

    assert result["applied"] == []
    assert result["failed"][0]["uncertain"] is True
    assert "could not confirm" in result["reply"].lower()


def test_delete_is_uncertain_when_the_row_may_remain(db, user):
    task = models.Task(id="audit-maybe-delete", user_id=user.id, text="Maybe deleted")
    db.add(task)
    db.commit()

    lose_ack(db, after_commit=False)
    try:
        result = execution.execute(db, user, {"op": "delete_task", "id": "audit-maybe-delete"},
                                   context={"today": TODAY})
    finally:
        restore(db)

    assert result["success"] is False and result["uncertain"] is True
    assert "could not confirm" in (result["error"] or "").lower()
    db.expire_all()
    assert db.get(models.Task, "audit-maybe-delete") is not None


# ── D. no retry, and the API tells the truth ──────────────────────────────

def test_no_automatic_retry_after_an_ambiguous_commit(db, user, conversation, scripted):
    before = counts(db, user)["tasks"]
    lose_ack(db)
    try:
        result, model = turn(db, user, conversation, scripted, "Create a task Pay audit rent",
                             {"reply": "Added.", "actions": [{"op": "add_task", "text": "Pay audit rent"}]})
    finally:
        restore(db)

    assert len(model.calls) == 1
    assert len(result["applied"]) + len(result["failed"]) == 1, "the action ran once"
    assert counts(db, user)["tasks"] == before + 1


def test_api_exposes_an_uncertain_outcome(db, user, conversation, client, scripted, monkeypatch):
    monkeypatch.setattr(execution, "_probe_row", lambda db, model, pk: (None, False))
    lose_ack(db, after_commit=False, only_task_text="Pay audit rent")
    try:
        scripted({"reply": "Added.", "actions": [{"op": "add_task", "text": "Pay audit rent"}]})
        response = client.post(f"/api/chat/conversations/{conversation.id}/messages",
                               json={"message": "Create a task Pay audit rent"},
                               headers={"X-User-Timezone": "Asia/Kolkata"})
    finally:
        restore(db)

    assert response.status_code == 200
    body = response.json()
    assert body["uncertain"] is True
    assert body["applied"] == []
    assert "could not confirm" in body["content"].lower()
    assert "sqlalchemy" not in body["content"].lower()
    assert "nothing was saved" not in body["content"].lower()
    assert body["graph_error"] == "", "this was a normal turn, not a graph failure"
