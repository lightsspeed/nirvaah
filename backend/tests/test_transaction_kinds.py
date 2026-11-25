"""Investments and savings are their own kinds, not expenses.

They move money to an asset instead of spending it, so they must be accepted by
the API and filterable, appear in the dashboard's own totals, and stay out of
expense reports and the assistant's spend summaries.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import models
from app.agent import analytics as agent_analytics
from app.agent import api as agent_api
from app.agent import authority, execution, planner
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user


TODAY = date(2026, 11, 13)


@pytest.fixture()
def account(db):
    row = models.User(name="Kinds", email="kinds@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def client(db, account):
    def _db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: account
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


def _tx(client, kind, amount, category, day=10):
    return client.post("/api/transactions", json={
        "kind": kind,
        "amount": amount,
        "category": category,
        "description": f"{kind} entry",
        "payment_method": "SBI",
        "txn_date": f"2026-11-{day:02d}",
    })


def test_investment_and_savings_kinds_are_accepted(client):
    assert _tx(client, "investment", 5000, "Mutual Fund").status_code == 200
    assert _tx(client, "savings", 2000, "Emergency Fund").status_code == 200

    invested = client.get("/api/transactions", params={"kind": "investment", "month": "all"}).json()
    saved = client.get("/api/transactions", params={"kind": "savings", "month": "all"}).json()
    assert [t["category"] for t in invested] == ["Mutual Fund"]
    assert [t["category"] for t in saved] == ["Emergency Fund"]


def test_an_unknown_kind_is_still_rejected(client):
    res = _tx(client, "transfer", 5000, "Mutual Fund")
    assert res.status_code == 400
    assert "investment" in res.json()["detail"]


def test_updating_an_expense_into_an_investment(client, db):
    created = _tx(client, "expense", 5000, "Other").json()
    updated = client.put(f"/api/transactions/{created['id']}", json={
        "kind": "investment",
        "amount": 5000,
        "category": "Stocks",
        "description": "Bought index fund",
        "payment_method": "SBI",
        "txn_date": "2026-11-10",
    })
    assert updated.status_code == 200
    assert db.get(models.Transaction, created["id"]).kind == "investment"


def test_dashboard_reports_contributions_separately(client):
    _tx(client, "income", 10000, "Salary", 1)
    _tx(client, "expense", 3000, "Groceries", 2)
    _tx(client, "investment", 2000, "Mutual Fund", 3)
    _tx(client, "savings", 1000, "Emergency Fund", 4)

    data = client.get("/api/dashboard", params={"month": "2026-11"}).json()

    assert data["income"] == 10000
    assert data["expenses"] == 3000
    assert data["invested"] == 2000
    assert data["saved"] == 1000
    assert data["savings"] == 7000
    assert [c["category"] for c in data["category_expenses"]] == ["Groceries"]


def test_expense_analytics_excludes_contributions(client):
    _tx(client, "income", 10000, "Salary", 1)
    _tx(client, "expense", 3000, "Groceries", 2)
    _tx(client, "investment", 2000, "Mutual Fund", 3)
    _tx(client, "savings", 1000, "Emergency Fund", 4)

    data = client.get("/api/analytics", params={"from": "2026-11", "to": "2026-11"}).json()

    assert data["total_income"] == 10000
    assert data["total_expense"] == 3000
    assert [c["category"] for c in data["category_breakdown"]] == ["Groceries"]


@pytest.fixture()
def chat(db, account):
    row = models.Conversation(id="conv-kinds", user_id=account.id, title="Kinds")
    db.add(row)
    db.commit()
    return row


def say(db, user, conversation, scripted, message, reply, actions=None):
    """One assistant turn, in the same shape the app drives it."""
    scripted({"reply": reply, "actions": actions or []})
    return agent_api.send_message(
        conversation.id,
        agent_api.MessageIn(message=message),
        db=db,
        user=user,
        today=TODAY,
        timezone_name="Asia/Kolkata",
    )


def test_execution_defaults_the_category_for_each_kind():
    invested = execution._transaction_fields({"kind": "investment", "amount": 5000}, creating=True)
    saved = execution._transaction_fields({"kind": "savings", "amount": 2000}, creating=True)
    changed = execution._transaction_fields({"kind": "savings"}, creating=False)

    assert invested["category"] == "Mutual Fund"
    assert saved["category"] == "Emergency Fund"
    assert changed["category"] == "Emergency Fund"
    with pytest.raises(ValueError):
        execution._transaction_fields({"kind": "transfer", "amount": 1}, creating=True)


def test_a_request_to_invest_or_save_authorises_a_transaction():
    assert authority.authorize_creation(
        "add_transaction", "Invest 5000 in a mutual fund SIP") is None
    assert authority.authorize_creation(
        "add_transaction", "I invested 5000 in stocks") is None
    assert authority.authorize_creation(
        "add_transaction", "Move 5000 to savings") is None
    # A question about investments is still a question, not a write.
    assert authority.authorize_creation(
        "add_transaction", "How much did I invest?") is not None


def test_investment_and_savings_reports_are_write_turns():
    assert planner._is_write_request(planner.normalise("I invested 5000 in a mutual fund"))
    assert planner._is_write_request(planner.normalise("Invest 5000 in a mutual fund SIP"))
    assert planner._is_write_request(planner.normalise("Move 5000 to savings"))
    assert not planner._is_write_request(planner.normalise("How much did I invest?"))


def test_the_assistant_adds_edits_and_deletes_a_contribution(db, account, chat, scripted):
    created = say(
        db, account, chat, scripted,
        "Invest 5000 in a mutual fund SIP.",
        "Added a 5,000 investment under Mutual Fund.",
        [{"op": "add_transaction", "kind": "investment", "amount": 5000,
          "category": "Mutual Fund", "description": "SIP contribution",
          "payment_method": "SBI", "txn_date": "2026-11-13"}],
    )
    assert len(created["applied"]) == 1, created
    row = db.query(models.Transaction).filter_by(
        user_id=account.id, description="SIP contribution").one()
    assert row.kind == "investment"

    edited = say(
        db, account, chat, scripted,
        "Move the SIP contribution to savings and make it 6000.",
        "Moved the SIP contribution to savings and updated it to 6,000.",
        [{"op": "update_transaction", "description": "SIP contribution",
          "kind": "savings", "amount": 6000}],
    )
    assert len(edited["applied"]) == 1, edited
    db.refresh(row)
    assert row.kind == "savings"
    assert row.category == "Emergency Fund"
    assert row.amount == Decimal("6000.00")

    proposed = say(
        db, account, chat, scripted,
        "Delete the SIP contribution.",
        "Delete the savings contribution?",
        [{"op": "delete_transaction", "description": "SIP contribution"}],
    )
    assert proposed["applied"] == []
    assert len(proposed["pending"]) == 1, proposed
    assert db.get(models.Transaction, row.id) is not None, "nothing is deleted before approval"

    # The confirmation the app sends after the proposal executes the delete.
    confirmed = execution.execute(
        db, account, {"op": "delete_transaction", "id": row.id},
        context={"today": TODAY, "tz": "UTC"},
    )
    assert confirmed["success"] and confirmed["verified"], confirmed
    assert db.query(models.Transaction).filter_by(id=row.id).first() is None


def test_the_assistant_monthly_buckets_ignore_contributions(client, db, account):
    _tx(client, "income", 10000, "Salary", 1)
    _tx(client, "expense", 3000, "Groceries", 2)
    _tx(client, "investment", 2000, "Mutual Fund", 3)
    _tx(client, "savings", 1000, "Emergency Fund", 4)

    buckets = agent_analytics._month_buckets(db, account, start=date(2026, 11, 1), end=date(2026, 11, 30))

    assert buckets["2026-11"]["income"] == 10000
    assert buckets["2026-11"]["expense"] == 3000
    assert buckets["2026-11"]["count"] == 2
