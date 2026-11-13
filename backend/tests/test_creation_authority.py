"""Task 27.6.1 — a creation runs only when the user's message asked for it.

The model proposes; the message authorizes. These tests drive the real graph
(`run_turn` → `guard_action` → `execution`) and check the database, so a refusal
is proven by row counts, not by the absence of an exception.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import graph
from app.agent.reply import claims_change
from app.ai import guard_action


TODAY = date(2026, 11, 13)


@pytest.fixture()
def client(db, user):
    """The real app wired to this test's session and user."""
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


def counts(db, user):
    return {
        "transactions": db.query(models.Transaction).filter_by(user_id=user.id).count(),
        "tasks": db.query(models.Task).filter_by(user_id=user.id).count(),
        "notes": db.query(models.Note).filter_by(user_id=user.id).count(),
        "journal": db.query(models.JournalEntry).filter_by(user_id=user.id).count(),
        "memories": db.query(models.MemoryFact).filter_by(user_id=user.id).count(),
    }


TRANSACTION_ACTION = {"op": "add_transaction", "kind": "expense", "amount": 5000,
                      "category": "Groceries", "description": "audit insert",
                      "payment_method": "UPI", "txn_date": "2026-05-10"}


# ── A. a question never creates money ───────────────────────────────────────

@pytest.mark.parametrize("message", [
    "How much did I spend in May?",
    "Show my grocery expenses",
    "What is my balance?",
    "How much did I save?",
    "Did I spend 500 on groceries?",
    "What did I spend at BigBasket?",
])
def test_a_question_cannot_create_a_transaction(db, user, conversation, scripted, message):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, message,
                     {"reply": "You spent ₹6,461 on groceries.", "actions": [TRANSACTION_ACTION]})

    assert result["applied"] == [] and result["pending"] == []
    assert result["failed"], "the refusal must be reported"
    assert counts(db, user)["transactions"] == before["transactions"]
    assert "nothing was saved" in result["reply"].lower()
    assert "₹6,461" not in result["reply"]


def test_add_up_is_arithmetic_not_a_creation(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Add up my grocery spending in May",
                     {"reply": "Adding.", "actions": [TRANSACTION_ACTION]})

    assert result["applied"] == []
    assert counts(db, user)["transactions"] == before["transactions"]
    assert "asks for a sum" in result["reply"]


def test_a_question_cannot_create_a_task(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "What tasks do I have?",
                     {"reply": "Adding a task.", "actions": [{"op": "add_task", "text": "Pay rent"}]})

    assert result["applied"] == []
    assert counts(db, user)["tasks"] == before["tasks"]
    assert "does not ask me to add a task" in result["reply"]


@pytest.mark.parametrize("op,extra,key", [
    ("add_budget", {"category": "Groceries", "monthly_limit": 5000}, "budgets"),
    ("add_goal", {"name": "Car", "target_amount": 500000}, "goals"),
    ("add_investment", {"name": "SIP", "invested_amount": 1000}, "investments"),
    ("add_liability", {"name": "Loan", "outstanding_amount": 1000}, "liabilities"),
    ("add_note", {"title": "Something"}, "notes"),
    ("add_journal", {"title": "Something"}, "journal"),
])
def test_every_creation_is_guarded(db, user, conversation, scripted, op, extra, key):
    before = counts(db, user)
    model_name = {"add_budget": models.Budget, "add_goal": models.Goal,
                  "add_investment": models.Investment, "add_liability": models.Liability,
                  "add_note": models.Note, "add_journal": models.JournalEntry}[op]
    before_rows = db.query(model_name).filter_by(user_id=user.id).count()

    result, _ = turn(db, user, conversation, scripted, "How much did I spend in May?",
                     {"reply": "Saving.", "actions": [{"op": op, **extra}]})

    assert result["applied"] == []
    assert db.query(model_name).filter_by(user_id=user.id).count() == before_rows
    assert "does not ask me to add" in result["reply"]
    assert counts(db, user)["transactions"] == before["transactions"]


# ── B. a mismatched noun does not authorize the wrong record type ──────────

def test_a_task_request_cannot_create_a_transaction(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Add a task to pay the electricity bill",
                     {"reply": "Adding.", "actions": [TRANSACTION_ACTION]})

    assert result["applied"] == []
    assert counts(db, user)["transactions"] == before["transactions"]


def test_an_expense_request_cannot_create_a_task(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Add a grocery expense",
                     {"reply": "Adding.", "actions": [{"op": "add_task", "text": "Pay rent"}]})

    assert result["applied"] == []
    assert counts(db, user)["tasks"] == before["tasks"]


# ── C. explicit requests still work ────────────────────────────────────────

def test_explicit_expense_creation_still_works(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Add a ₹500 grocery expense for 10 May 2026",
                     {"reply": "Added.", "actions": [TRANSACTION_ACTION]})

    assert result["applied"] and result["applied"][0]["verified"] is True
    assert counts(db, user)["transactions"] == before["transactions"] + 1
    row = (db.query(models.Transaction).filter_by(user_id=user.id, description="audit insert")
           .order_by(models.Transaction.id.desc()).first())
    assert row is not None and row.amount == 5000 and row.category == "Groceries"


def test_explicit_income_creation_still_works(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Record my salary of ₹80,000 in May 2026",
                     {"reply": "Recorded.", "actions": [
                         {"op": "add_transaction", "kind": "income", "amount": 80000,
                          "category": "Salary", "description": "May salary",
                          "payment_method": "SBI", "txn_date": "2026-05-01"}]})

    assert result["applied"] and result["applied"][0]["verified"] is True
    assert counts(db, user)["transactions"] == before["transactions"] + 1


def test_explicit_task_creation_still_works(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Create a task to pay rent on 20 November",
                     {"reply": "Added.", "actions": [
                         {"op": "add_task", "text": "Pay rent", "due": "2026-11-20"}]})

    assert result["applied"] and result["applied"][0]["verified"] is True
    assert counts(db, user)["tasks"] == before["tasks"] + 1


def test_a_reported_spend_is_still_recorded(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "I spent 500 on groceries today",
                     {"reply": "Recorded.", "actions": [
                         {"op": "add_transaction", "kind": "expense", "amount": 500,
                          "category": "Groceries", "payment_method": "UPI",
                          "txn_date": "2026-11-13"}]})

    assert result["applied"], result["failed"]
    assert counts(db, user)["transactions"] == before["transactions"] + 1


def test_a_note_request_is_still_recorded(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Note that the wifi password is on the fridge",
                     {"reply": "Noted.", "actions": [{"op": "add_note", "title": "Wifi password"}]})

    assert result["applied"], result["failed"]
    assert counts(db, user)["notes"] == before["notes"] + 1


# ── D. everything that already validated still validates ───────────────────

def test_amount_validation_still_runs_after_authorization(db, user, conversation, scripted):
    before = counts(db, user)
    result, _ = turn(db, user, conversation, scripted, "Add a grocery expense",
                     {"reply": "Added.", "actions": [
                         {"op": "add_transaction", "kind": "expense", "amount": -500,
                          "category": "Groceries", "txn_date": "2026-11-13"}]})

    assert result["applied"] == []
    assert "greater than zero" in (result["failed"][0].get("error") or "")
    assert counts(db, user)["transactions"] == before["transactions"]


def test_a_refusal_never_claims_success(db, user, conversation, scripted):
    result, _ = turn(db, user, conversation, scripted, "How much did I spend in May?",
                     {"reply": "Added the expense.", "actions": [TRANSACTION_ACTION]})

    assert claims_change(result["reply"]) is False
    assert "nothing was saved" in result["reply"].lower()


def test_repeated_blocked_attempts_change_nothing(db, user, conversation, scripted):
    before = counts(db, user)
    for number in (1, 2, 3):
        result, _ = turn(db, user, conversation, scripted, "How much did I spend in May?",
                         {"reply": "Adding.", "actions": [TRANSACTION_ACTION]}, number=number)
        assert result["applied"] == []

    assert counts(db, user) == before


# ── E. memory requests are unaffected ─────────────────────────────────────

def test_a_remember_action_is_not_treated_as_a_creation(db, user):
    assert guard_action(db, user, {"op": "remember", "fact": "rent is due on the 5th"},
                        "Remember that rent is due on the 5th") is None


def test_a_memory_request_still_stores_the_fact(db, user, conversation, client, scripted):
    before = counts(db, user)
    scripted({"reply": "Noted.", "actions": []})
    response = client.post(f"/api/chat/conversations/{conversation.id}/messages",
                           json={"message": "Remember that my rent is due on the 5th"},
                           headers={"X-User-Timezone": "Asia/Kolkata"})
    assert response.status_code == 200
    assert counts(db, user)["memories"] == before["memories"] + 1
    stored = (db.query(models.MemoryFact).filter_by(user_id=user.id)
              .order_by(models.MemoryFact.id.desc()).first())
    assert "rent is due" in stored.fact
