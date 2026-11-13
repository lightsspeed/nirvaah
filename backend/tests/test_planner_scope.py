"""Task 27.5.3 — the thread's period survives a change of scope.

F5: comparing two categories inside a month thread compares that month, not all
time. F6: "show all expenses" changes the category scope, not the period.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app import models
from app.agent import analytics, planner


TODAY = date(2026, 11, 13)


@pytest.fixture()
def ledger(db):
    """A clean ledger of its own: May and June, nothing borrowed from other suites.

    May: Groceries 1500 (2 rows), Dining Out 800, Fuel 500, salary 90000.
    June: Groceries 700, Dining Out 400, salary 88000.
    """
    user = models.User(name="Scope User", email="scope@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    rows = [
        ("expense", "Groceries", "BigBasket", 900, date(2026, 5, 3)),
        ("expense", "Groceries", "More Supermarket", 600, date(2026, 5, 9)),
        ("expense", "Dining Out", "Truffles", 800, date(2026, 5, 12)),
        ("expense", "Fuel", "HP Petrol", 500, date(2026, 5, 5)),
        ("expense", "Groceries", "BigBasket", 700, date(2026, 6, 2)),
        ("expense", "Dining Out", "Truffles", 400, date(2026, 6, 7)),
        ("income", "Salary", "Employer", 90000, date(2026, 5, 1)),
        ("income", "Salary", "Employer", 88000, date(2026, 6, 1)),
    ]
    for kind, category, description, amount, when in rows:
        db.add(models.Transaction(user_id=user.id, kind=kind, amount=Decimal(str(amount)),
                                  category=category, description=description,
                                  payment_method="UPI", txn_date=when))
    db.commit()
    return user


@pytest.fixture()
def client(db, ledger):
    """The real app, wired to this test's session and this test's user."""
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app
    from app.security import get_current_user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: ledger
    yield TestClient(app)
    app.dependency_overrides.clear()


def may_thread(intent="list_transactions", category="Groceries", month="2026-05", kind="expense",
               turn=1, pair=None):
    return {"intent": intent, "category": category, "month": month, "kind": kind,
            "comparison_target": pair, "turn": turn, "updated_at": "2026-11-13T10:00:00Z"}


# ── F5: a comparison inherits the month the thread is already on ───────────

def test_a_comparison_inherits_the_thread_month(db, ledger):
    first = planner.analyse(db, ledger, "Show my grocery expenses in May.", today=TODAY)
    assert first["intent"] == "list_transactions"

    second = planner.analyse(db, ledger, "Compare groceries and dining out.", today=TODAY,
                             context=first["context"], turn=2)

    assert second["intent"] == "compare_categories"
    assert second["facts"]["month"] == "2026-05"
    totals = {row["category"]: row["total"] for row in second["facts"]["categories"]}
    assert totals == {"Groceries": 1500.0, "Dining Out": 800.0}
    assert second["facts"]["higher"] == "Groceries"
    assert second["context"]["month"] == "2026-05"
    assert second["context"]["comparison_target"] == "Dining Out"


def test_the_inherited_month_reaches_the_sql(db, ledger, monkeypatch):
    seen = []
    real = analytics.compare_categories

    def spy(*args, **kwargs):
        seen.append(kwargs.get("month"))
        return real(*args, **kwargs)

    monkeypatch.setattr(analytics, "compare_categories", spy)
    planner.analyse(db, ledger, "Compare groceries and dining out.", today=TODAY,
                    context=may_thread(), turn=2)

    assert seen == ["2026-05"]


def test_an_explicit_month_overrides_the_inherited_one(db, ledger):
    analysis = planner.analyse(db, ledger, "Compare groceries and dining out in June.",
                               today=TODAY, context=may_thread(), turn=2)

    assert analysis["facts"]["month"] == "2026-06"
    totals = {row["category"]: row["total"] for row in analysis["facts"]["categories"]}
    assert totals == {"Groceries": 700.0, "Dining Out": 400.0}
    assert analysis["context"]["month"] == "2026-06"


def test_the_comparison_follow_up_keeps_the_pair_and_month(db, ledger):
    first = planner.analyse(db, ledger, "Show my grocery expenses in May.", today=TODAY)
    second = planner.analyse(db, ledger, "Compare groceries and dining out.", today=TODAY,
                             context=first["context"], turn=2)

    third = planner.analyse(db, ledger, "Which one was higher?", today=TODAY,
                            context=second["context"], turn=3)

    assert third["intent"] == "compare_categories"
    assert third["facts"]["month"] == "2026-05"
    assert third["facts"]["higher"] == "Groceries"
    assert third["context"]["comparison_target"] == "Dining Out"
    assert third["context"]["month"] == "2026-05"


def test_an_expired_thread_supplies_no_month(db, ledger):
    stale = may_thread(turn=1)

    analysis = planner.analyse(db, ledger, "Compare groceries and dining out.", today=TODAY,
                               context=stale, turn=1 + planner.CONTEXT_TTL_TURNS + 1)

    assert analysis["facts"]["month"] is None, "an expired thread must not lend its month"


def test_a_reset_thread_supplies_no_month(db, ledger):
    reset = planner.analyse(db, ledger, "How much did I spend overall?", today=TODAY,
                            context=may_thread(), turn=2)
    assert reset["context"] is None

    after = planner.analyse(db, ledger, "Compare groceries and dining out.", today=TODAY,
                            context=reset["context"], turn=3)

    assert after["facts"]["month"] is None
    assert after["context"]["month"] is None


def test_an_unknown_category_never_compares_broadly(db, ledger, monkeypatch):
    called = []
    real = analytics.compare_categories
    monkeypatch.setattr(analytics, "compare_categories",
                        lambda *a, **k: called.append(k) or real(*a, **k))

    analysis = planner.analyse(db, ledger, "Compare groceries and yachts.", today=TODAY,
                               context=may_thread(), turn=2)

    assert analysis["intent"] == "unknown_category"
    assert analysis["facts"]["month"] == "2026-05"
    assert called == []


def test_a_write_request_never_runs_a_comparison(db, ledger, monkeypatch):
    called = []
    monkeypatch.setattr(analytics, "compare_categories", lambda *a, **k: called.append(k))

    analysis = planner.analyse(db, ledger, "Make it a task to pay rent on 20 November.",
                               today=TODAY, context=may_thread(turn=1, pair="Fuel"), turn=2)

    assert analysis["intent"] is None
    assert analysis["facts"] is None
    assert called == []


# ── F6: all categories keeps the period ───────────────────────────────────

def test_all_expenses_keeps_the_thread_month(db, ledger):
    first = planner.analyse(db, ledger, "Show my grocery expenses in May.", today=TODAY)
    assert first["facts"]["category"] == "Groceries"

    second = planner.analyse(db, ledger, "Now show all expenses.", today=TODAY,
                             context=first["context"], turn=2)

    assert second["intent"] == "list_transactions"
    assert second["facts"]["category"] is None
    assert second["facts"]["month"] == "2026-05"
    assert second["facts"]["count"] == 4
    assert second["facts"]["total"] == 2800.0
    assert second["context"]["category"] is None
    assert second["context"]["month"] == "2026-05"
    assert second["context"]["kind"] == "expense"


def test_the_all_category_scope_survives_a_month_change(db, ledger):
    first = planner.analyse(db, ledger, "Show my grocery expenses in May.", today=TODAY)
    second = planner.analyse(db, ledger, "Now show all expenses.", today=TODAY,
                             context=first["context"], turn=2)

    third = planner.analyse(db, ledger, "What about June?", today=TODAY,
                            context=second["context"], turn=3)

    assert third["intent"] == "list_transactions"
    assert third["facts"]["category"] is None
    assert third["facts"]["month"] == "2026-06"
    assert third["facts"]["count"] == 2
    assert third["facts"]["total"] == 1100.0
    assert third["context"]["month"] == "2026-06"


def test_an_explicit_month_overrides_the_thread_period(db, ledger):
    analysis = planner.analyse(db, ledger, "Show all expenses from September.", today=TODAY,
                               context=may_thread(), turn=2)

    assert analysis["facts"]["month"] == "2026-09"
    assert analysis["facts"]["category"] is None
    assert analysis["context"]["month"] == "2026-09"


def test_overall_clears_both_category_and_month(db, ledger):
    analysis = planner.analyse(db, ledger, "How much did I spend overall?", today=TODAY,
                               context=may_thread(), turn=2)

    assert analysis["context"] is None
    assert analysis["facts"] is None


def test_a_reset_does_not_resurrect_the_month(db, ledger):
    reset = planner.analyse(db, ledger, "How much did I spend overall?", today=TODAY,
                            context=may_thread(), turn=2)

    after = planner.analyse(db, ledger, "Now show all expenses.", today=TODAY,
                            context=reset["context"], turn=3)

    assert after["facts"]["month"] is None
    assert after["context"] is None


def test_income_and_expense_scopes_stay_distinct(db, ledger):
    analysis = planner.analyse(db, ledger, "Show all income transactions in May.", today=TODAY,
                               context=may_thread(), turn=2)

    assert analysis["facts"]["kind"] == "income"
    assert analysis["facts"]["month"] == "2026-05"
    assert analysis["facts"]["total"] == 90000.0
    assert analysis["context"]["kind"] == "income"

    follow = planner.analyse(db, ledger, "What about June?", today=TODAY,
                             context=analysis["context"], turn=3)

    assert follow["facts"]["kind"] == "income"
    assert follow["facts"]["month"] == "2026-06"
    assert follow["facts"]["total"] == 88000.0


# ── the same two conversations over the real API ──────────────────────────

def _conversation(client, title="scope"):
    response = client.post("/api/chat/conversations", json={"title": title})
    assert response.status_code == 200
    return response.json()["id"]


def _ask(client, conversation_id, message):
    response = client.post(f"/api/chat/conversations/{conversation_id}/messages",
                           json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def _stored_analytics(db, conversation_id):
    row = (db.query(models.ChatMessage)
           .filter(models.ChatMessage.conversation_id == conversation_id,
                   models.ChatMessage.role == "assistant")
           .order_by(models.ChatMessage.id.desc()).first())
    return json.loads(row.meta)["analytics"]


def test_the_may_comparison_survives_the_api(db, ledger, client, scripted):
    scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client, "f5")

    _ask(client, conversation_id, "Show my grocery expenses in May.")
    _ask(client, conversation_id, "Compare groceries and dining out.")

    stored = _stored_analytics(db, conversation_id)
    assert stored["intent"] == "compare_categories"
    assert stored["month"] == "2026-05"
    assert stored["comparison_target"] == "Dining Out"

    _ask(client, conversation_id, "Which one was higher?")
    stored = _stored_analytics(db, conversation_id)
    assert stored["month"] == "2026-05", "the answer must stay on May"


def test_all_expenses_keeps_the_month_through_the_api(db, ledger, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client, "f6")

    _ask(client, conversation_id, "Show my grocery expenses in May.")
    _ask(client, conversation_id, "Now show all expenses.")

    stored = _stored_analytics(db, conversation_id)
    assert stored["category"] is None
    assert stored["month"] == "2026-05"

    _ask(client, conversation_id, "What about June?")
    assert '"month": "2026-06"' in model.last_system
    assert '"category": null' in model.last_system
