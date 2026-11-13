"""Task 28.2 — a reported transaction is a write turn, and "latest" is not a filter.

Both behaviours were measured in Task 28.1: a spend report left `category=Groceries`
in the thread and "show me my latest transactions" searched for the word "latest".
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import graph, planner


TODAY = date(2026, 11, 13)


@pytest.fixture()
def wired(db, user):
    """Expose the session and user to the helper above (module-level globals)."""
    global db_session, user_row
    db_session, user_row = db, user
    return user


# ── A. first-person money reports are write turns ─────────────────────────

@pytest.mark.parametrize("message", [
    "I spent ₹1,500 on groceries today.",
    "I paid 500 for fuel.",
    "We bought groceries for 1200.",
    "I earned 5000 today.",
    "I received 2000 from my client.",
    "I got paid 30000.",
    "I have spent 750 on transport",
])
def test_a_money_report_runs_no_analytics(wired, message):
    analysis = planner.analyse(db_session, user_row, message, today=TODAY)

    assert analysis["intent"] is None
    assert analysis["facts"] is None
    assert analysis["context"] is None, "a write turn starts no analytics thread"


def test_a_money_report_does_not_discard_an_existing_thread(wired):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = planner.analyse(db_session, user_row, "I spent 1500 on groceries today",
                               today=TODAY, context=prior, turn=2)

    assert analysis["intent"] is None
    assert analysis["context"] == prior, "the turn is a write, not a new topic"


@pytest.mark.parametrize("message", [
    "How much did I spend in May?",
    "What did I spend on groceries?",
    "Show my latest transactions.",
    "Compare my spending this month",
    "I spent too much in May",
    "I paid the rent",
    "I earned a good bonus this year",
])
def test_money_questions_are_not_write_turns(message):
    assert planner._is_write_request(planner.normalise(message)) is False


@pytest.mark.parametrize("message,intent", [
    ("How much did I spend in May?", "month_summary"),
    ("What did I spend on groceries?", "category_series"),
    ("Show my latest transactions.", "list_transactions"),
    ("I spent too much in May", "month_summary"),
])
def test_money_questions_still_reach_their_analytics(wired, message, intent):
    assert planner.analyse(db_session, user_row, message, today=TODAY)["intent"] == intent


def test_a_report_leaves_the_database_alone_until_the_model_acts(wired):
    before = db_session.query(models.Transaction).count()
    planner.analyse(db_session, user_row, "I spent ₹1,500 on groceries today.", today=TODAY)
    after = db_session.query(models.Transaction).count()

    assert after == before, "the planner reads; only the executor writes"


# ── B. "latest"/"newest"/"oldest"/"first" are not text filters ───────────

@pytest.mark.parametrize("message", [
    "Show me my latest transactions.",
    "Show my newest transactions",
    "List my oldest transactions",
    "Show me the first transactions",
])
def test_latest_transactions_lists_rows(wired, message):
    analysis = planner.analyse(db_session, user_row, message, today=TODAY)

    assert analysis["intent"] == "list_transactions"
    facts = analysis["facts"]
    assert facts["text"] is None, "the word 'latest' must not become a merchant filter"
    assert facts["count"] > 0
    assert facts["status"] == "ok"


def test_a_real_merchant_listing_still_filters(wired):
    analysis = planner.analyse(db_session, user_row, "Show me my Cafeteria transactions",
                               today=TODAY)

    assert analysis["intent"] == "list_transactions"
    assert analysis["facts"]["text"] == "cafeteria"


# ── C. the journey: create, then ask how much was spent ──────────────────

def test_the_thread_stays_clean_after_creating_a_transaction(wired, conversation, scripted):
    scripted({"reply": "Added ₹1,500 under Groceries.",
                      "actions": [{"op": "add_transaction", "kind": "expense", "amount": 1500,
                                   "category": "Groceries", "payment_method": "UPI"}]})
    created = graph.run_turn(db_session, user_row, conversation.id,
                             "I spent ₹1,500 on groceries today.", [], turn=1, today=TODAY)
    assert created["applied"] and created["applied"][0]["verified"] is True

    assert created["analytics"]["intent"] is None
    assert created["analytics"]["context"] is None, "the creation stores no analytics context"

    scripted({"reply": "You have spent ₹350 this month.", "actions": []})
    follow = graph.run_turn(db_session, user_row, conversation.id,
                            "How much have I spent this month?", [], turn=2, today=TODAY)

    assert follow["analytics"]["intent"] == "month_summary", (
        "the creation must not narrow the next question to its category")
    # 350 of seeded November spending plus the 1,500 just created — all categories.
    assert follow["analytics"]["facts"]["expense"] == 1850.0
    assert follow["analytics"]["facts"]["month"] == "2026-11"
