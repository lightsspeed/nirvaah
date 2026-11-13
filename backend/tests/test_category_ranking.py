"""Task 28.3 — category spending ranking, aggregated and ordered by PostgreSQL.

The seeded ledger (conftest) has, over all time: Office Eats 4,067.00 (2 rows),
Dining Out 2,494.62 (3), Groceries 900.00 (1) — ₹7,461.62 of expenses — plus two
salary income rows that must never be ranked.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import analytics, graph, planner


TODAY = date(2026, 11, 13)

ALL_TIME = [
    ("Office Eats", 4067.00, 2),
    ("Dining Out", 2494.62, 3),
    ("Groceries", 900.00, 1),
]


def ranked(facts):
    return [(row["category"], row["total"], row["count"]) for row in facts["categories"]]


def analyse(db, user, message, context=None, turn=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn)


# ── the aggregation ─────────────────────────────────────────────────────────

def test_ranking_orders_categories_by_total_expense(db, user):
    facts = analytics.category_ranking(db, user)

    assert facts["status"] == "ok"
    assert facts["scope"] == "all time"
    assert ranked(facts) == ALL_TIME
    assert facts["total"] == 7461.62
    assert facts["count"] == 6
    assert facts["top"] == facts["categories"][0]
    assert facts["top"]["category"] == "Office Eats"


def test_shares_describe_the_whole_window(db, user):
    facts = analytics.category_ranking(db, user)

    assert [row["share_pct"] for row in facts["categories"]] == [54.5, 33.4, 12.1]
    assert sum(row["share_pct"] for row in facts["categories"]) == pytest.approx(100.0, abs=0.2)


def test_income_is_never_ranked(db, user):
    facts = analytics.category_ranking(db, user)

    assert "Salary" not in [row["category"] for row in facts["categories"]]
    assert facts["total"] == 7461.62, "the two salary rows (₹1,78,000) stay out of the window"


def test_another_users_spending_is_never_ranked(db, user):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=99999.00,
                              category="Groceries", description="their shop",
                              payment_method="UPI", txn_date=date(2026, 6, 5)))
    db.commit()

    facts = analytics.category_ranking(db, user)

    assert ranked(facts) == ALL_TIME
    assert facts["total"] == 7461.62


def test_current_month_window(db, user):
    facts = analytics.category_ranking(db, user, month="2026-11")

    assert facts["scope"] == "2026-11"
    assert ranked(facts) == [("Dining Out", 350.00, 1)]


def test_current_year_window(db, user):
    facts = analytics.category_ranking(db, user, year=2026)

    assert facts["scope"] == "2026"
    assert ranked(facts) == ALL_TIME

    assert analytics.category_ranking(db, user, year=2025)["status"] == "no_data"


def test_top_n_limit(db, user):
    assert ranked(analytics.category_ranking(db, user, limit=2)) == ALL_TIME[:2]
    assert ranked(analytics.category_ranking(db, user, limit=1)) == ALL_TIME[:1]
    # An out-of-range request is clamped, never an error.
    assert analytics.category_ranking(db, user, limit=0)["limit"] == 1
    assert analytics.category_ranking(db, user, limit=99)["limit"] == 20


def test_a_window_with_no_expenses_is_no_data_not_zero(db, user):
    facts = analytics.category_ranking(db, user, month="2026-03")

    assert facts["status"] == "no_data"
    assert facts["categories"] == []
    assert facts["top"] is None


def test_a_missing_category_is_reported_as_other(db, user):
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=40.00, category="",
                              description="unlabelled", payment_method="Cash",
                              txn_date=date(2026, 7, 2)))
    db.commit()

    facts = analytics.category_ranking(db, user)

    assert ("Other", 40.00, 1) in ranked(facts)


def test_case_variants_of_one_category_are_one_rank(db, user):
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=100.00,
                              category="groceries", description="corner shop",
                              payment_method="Cash", txn_date=date(2026, 7, 3)))
    db.commit()

    facts = analytics.category_ranking(db, user)
    groceries = [row for row in facts["categories"] if row["category"].lower() == "groceries"]

    assert len(groceries) == 1
    assert groceries[0]["total"] == 1000.00
    assert groceries[0]["count"] == 2


# ── routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Which category did I spend the most on?",
    "Which category has the highest spending this month?",
    "Show my top 5 spending categories this month.",
    "What are my top spending categories this year?",
    "Rank my expenses by category.",
    "Rank my spending categories for this year.",
])
def test_ranking_questions_reach_the_ranking(db, user, message):
    analysis = analyse(db, user, message)

    assert analysis["intent"] == "category_ranking"
    assert analysis["facts"]["status"] == "ok"
    assert "scope" in analysis["facts"]


@pytest.mark.parametrize("message,scope,limit", [
    ("Which category did I spend the most on?", "all time", 5),
    ("Which category has the highest spending this month?", "2026-11", 5),
    ("Show my top 5 spending categories this month.", "2026-11", 5),
    ("What are my top spending categories this year?", "2026", 5),
    ("Show my top 2 spending categories", "all time", 2),
])
def test_scope_and_limit_come_from_the_message(db, user, message, scope, limit):
    facts = analyse(db, user, message)["facts"]

    assert facts["scope"] == scope
    assert facts["limit"] == limit
    assert len(facts["categories"]) <= limit


def test_a_ranking_never_inherits_the_carried_category(db, user):
    prior = {"intent": "category_series", "category": "Groceries", "month": None,
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, user, "Which category did I spend the most on?", context=prior)

    assert analysis["intent"] == "category_ranking"
    assert analysis["facts"]["scope"] == "all time"
    assert analysis["facts"]["categories"][0]["category"] == "Office Eats"
    assert analysis["context"]["category"] is None
    assert analysis["context"]["intent"] == "category_ranking"


def test_a_ranking_keeps_its_shape_for_a_month_followup(db, user):
    first = analyse(db, user, "Rank my expenses by category.")
    follow = analyse(db, user, "What about June?", context=first["context"], turn=2)

    assert follow["intent"] == "category_ranking"
    assert follow["facts"]["scope"] == "2026-06"
    assert ranked(follow["facts"]) == [("Dining Out", 2144.62, 2), ("Groceries", 900.00, 1)]


def test_an_income_ranking_is_explicit(db, user):
    facts = analyse(db, user, "Rank my income categories by amount")["facts"]

    assert facts["status"] == "ok"
    assert facts["kind"] == "income"
    assert ranked(facts) == [("Salary", 178000.00, 2)]


# ── neighbours keep their behaviour ────────────────────────────────────────

def test_a_category_amount_question_is_still_a_series(db, user):
    analysis = analyse(db, user, "How much did I spend on groceries?")

    assert analysis["intent"] == "category_series"
    assert analysis["facts"]["category"] == "Groceries"


def test_a_merchant_question_is_still_a_merchant_question(db, user):
    analysis = analyse(db, user, "Which merchant did I spend the most on?")

    assert analysis["intent"] == "merchants"


def test_a_category_in_a_month_is_still_category_month(db, user):
    analysis = analyse(db, user, "How much did I spend on Dining Out in June?")

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["month"] == "2026-06"


def test_a_comparison_is_still_a_comparison(db, user):
    analysis = analyse(db, user, "Compare groceries and dining out")

    assert analysis["intent"] == "compare_categories"


# ── the model is given the ranks, not a pile of rows ───────────────────────

def test_the_prompt_carries_the_ranking_facts(db, user, conversation, scripted):
    model = scripted({"reply": "Office Eats took the most, ₹4,067.00.", "actions": []})

    turn = graph.run_turn(db, user, conversation.id, "Which category did I spend the most on?",
                          [], turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "category_ranking"
    prompt = model.last_system
    assert "category_ranking" in prompt
    assert "Office Eats" in prompt
    assert "4067.0" in prompt
    assert "share_pct" in prompt
