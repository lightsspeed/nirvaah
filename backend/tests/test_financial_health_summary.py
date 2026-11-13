"""Task 28.5 — the monthly financial health summary, composed from existing analytics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import models
from app.agent import analytics, graph, planner


TODAY = date(2026, 11, 13)

LEDGER = [
    # November: salary, five ordinary dining rows + one outlier, three other categories
    ("income", 90000.00, "Salary", "November salary", date(2026, 11, 1)),
    ("expense", 600, "Dining Out", "cafe", date(2026, 11, 3)),
    ("expense", 620, "Dining Out", "cafe", date(2026, 11, 5)),
    ("expense", 580, "Dining Out", "cafe", date(2026, 11, 7)),
    ("expense", 610, "Dining Out", "cafe", date(2026, 11, 9)),
    ("expense", 640, "Dining Out", "cafe", date(2026, 11, 11)),
    ("expense", 8000, "Dining Out", "big dinner", date(2026, 11, 12)),
    ("expense", 1200.56, "Groceries", "shop", date(2026, 11, 4)),
    ("expense", 3000, "Fuel", "pump", date(2026, 11, 6)),
    ("expense", 900, "Subscription", "netflix", date(2026, 11, 8)),
    # October: income only
    ("income", 50000, "Salary", "October salary", date(2026, 10, 1)),
    # September: expenses only
    ("expense", 700, "Dining Out", "cafe", date(2026, 9, 3)),
    ("expense", 300, "Groceries", "shop", date(2026, 9, 4)),
]


@pytest.fixture()
def books(db):
    row = models.User(name="Books", email="books@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    for kind, amount, category, description, when in LEDGER:
        db.add(models.Transaction(user_id=row.id, kind=kind, amount=amount, category=category,
                                  description=description, payment_method="UPI", txn_date=when))
    db.commit()
    return row


def summary(db, user, **kwargs):
    return analytics.financial_health_summary(db, user, today=TODAY, **kwargs)


def analyse(db, user, message, context=None, turn=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn)


# ── the parts ──────────────────────────────────────────────────────────────

def test_income_and_expense_totals(db, books):
    facts = summary(db, books, month="2026-11")

    assert facts["status"] == "ok"
    assert facts["income"] == 90000.0
    assert facts["expenses"] == 16150.56
    assert facts["counts"] == {"income": 1, "expense": 9}


def test_net_cash_flow_is_income_minus_expenses(db, books):
    facts = summary(db, books, month="2026-11")

    assert facts["net_cash_flow"] == pytest.approx(73849.44)
    assert facts["net_cash_flow"] == pytest.approx(facts["income"] - facts["expenses"])


def test_totals_are_exact_to_the_paisa(db, books):
    # 1,200.56 + 600 + 620 + 580 + 610 + 640 + 8,000 + 3,000 + 900
    facts = summary(db, books, month="2026-11")

    assert Decimal(str(facts["expenses"])) == Decimal("16150.56")
    assert Decimal(str(facts["net_cash_flow"])) == Decimal("73849.44")


def test_top_three_expense_categories(db, books):
    facts = summary(db, books, month="2026-11")

    assert [(c["category"], c["total"]) for c in facts["top_categories"]] == [
        ("Dining Out", 11050.0), ("Fuel", 3000.0), ("Groceries", 1200.56)]
    assert len(facts["top_categories"]) == 3


def test_income_never_appears_in_the_category_ranking(db, books):
    facts = summary(db, books, month="2026-11")

    assert "Salary" not in [c["category"] for c in facts["top_categories"]]
    assert sum(c["total"] for c in facts["top_categories"]) < facts["income"]


def test_biggest_expense_is_the_largest_row(db, books):
    facts = summary(db, books, month="2026-11")

    assert facts["biggest_expense"] == {"date": "2026-11-12", "amount": 8000.0,
                                        "category": "Dining Out", "description": "big dinner"}


def test_unusual_expenses_come_from_the_detector(db, books):
    facts = summary(db, books, month="2026-11")
    unusual = facts["unusual"]

    assert unusual["status"] == "ok"
    assert unusual["count"] == 1
    # The baseline is the category's whole history, not the window: September's
    # ₹700 dining row is part of it, so the median of the other six is ₹615.
    assert [(i["date"], i["amount"], i["median"], i["history_count"])
            for i in unusual["items"]] == [("2026-11-12", 8000.0, 615.0, 6)]
    assert unusual["categories_needing_history"], "thin categories are named, not judged"


def test_insufficient_history_survives_composition(db):
    user = models.User(name="Thin", email="thin@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for day, amount in ((1, 500), (2, 600)):
        db.add(models.Transaction(user_id=user.id, kind="expense", amount=amount,
                                  category="Fuel", description="pump", payment_method="UPI",
                                  txn_date=date(2026, 11, day)))
    db.commit()

    facts = summary(db, user, month="2026-11")

    assert facts["status"] == "ok"
    assert facts["unusual"]["status"] == "insufficient_history"
    assert facts["unusual"]["categories_needing_history"] == ["Fuel"]
    assert facts["unusual"]["items"] == []


# ── periods and partial data ───────────────────────────────────────────────

def test_period_metadata(db, books):
    month = summary(db, books, month="2026-11")["period"]
    year = summary(db, books, year=2026)["period"]

    assert month == {"request": "2026-11", "kind": "month",
                     "start": "2026-11-01", "end": "2026-11-30"}
    assert year == {"request": "2026", "kind": "year",
                    "start": "2026-01-01", "end": "2026-12-31"}


def test_the_year_window_adds_every_month(db, books):
    facts = summary(db, books, year=2026)

    assert facts["income"] == 140000.0
    assert facts["expenses"] == 17150.56
    assert facts["counts"] == {"income": 2, "expense": 11}


def test_no_period_means_the_current_month(db, books):
    facts = summary(db, books)

    assert facts["period"]["request"] == "2026-11"
    assert facts["income"] == 90000.0


def test_a_period_with_income_but_no_expenses(db, books):
    facts = summary(db, books, month="2026-10")

    assert facts["status"] == "ok"
    assert facts["income"] == 50000.0
    assert facts["expenses"] == 0.0
    assert facts["counts"] == {"income": 1, "expense": 0}
    assert facts["top_categories"] == []
    assert facts["biggest_expense"] is None
    assert facts["unusual"]["status"] == "no_data"


def test_a_period_with_expenses_but_no_income(db, books):
    facts = summary(db, books, month="2026-09")

    assert facts["income"] == 0.0
    assert facts["counts"] == {"income": 0, "expense": 2}
    assert facts["expenses"] == 1000.0
    assert facts["net_cash_flow"] == -1000.0


def test_an_empty_period_is_no_data(db, books):
    facts = summary(db, books, month="2026-03")

    assert facts["status"] == "no_data"
    assert facts["counts"] == {"income": 0, "expense": 0}
    assert facts["top_categories"] == []
    assert facts["biggest_expense"] is None
    assert "2026-03" in facts["message"]


def test_another_users_transactions_are_excluded(db, books):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=99999,
                              category="Groceries", description="theirs",
                              payment_method="UPI", txn_date=date(2026, 11, 5)))
    db.commit()

    facts = summary(db, books, month="2026-11")

    assert facts["expenses"] == 16150.56
    assert facts["biggest_expense"]["amount"] == 8000.0


# ── routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,period", [
    ("Give me my financial health summary for this month.", "2026-11"),
    ("How am I doing financially this month?", "2026-11"),
    ("Summarise my finances for October.", "2026-10"),
    ("Give me my financial overview for this year.", "2026"),
])
def test_summary_requests_reach_the_summary(db, books, message, period):
    analysis = analyse(db, books, message)

    assert analysis["intent"] == "financial_health_summary"
    assert analysis["facts"]["period"]["request"] == period


def test_the_summary_outranks_individual_intents(db, books):
    analysis = analyse(db, books, "Summarise my finances for October.")

    assert analysis["intent"] == "financial_health_summary"
    assert analysis["facts"]["income"] == 50000.0


def test_a_carried_category_or_merchant_does_not_narrow_it(db, books):
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, books, "Give me my financial health summary for this month.",
                       context=prior, turn=2)

    assert [c["category"] for c in analysis["facts"]["top_categories"]] == [
        "Dining Out", "Fuel", "Groceries"]
    assert analysis["facts"]["expenses"] == 16150.56, "the whole month, not one category"
    assert analysis["context"]["category"] is None


def test_a_month_followup_stays_a_summary(db, books):
    first = analyse(db, books, "Give me my financial health summary for this month.")
    follow = analyse(db, books, "What about September?", context=first["context"], turn=2)

    assert follow["intent"] == "financial_health_summary"
    assert follow["facts"]["period"]["request"] == "2026-09"
    assert follow["facts"]["expenses"] == 1000.0


def test_individual_intents_are_unchanged(db, books):
    assert analyse(db, books, "Which category did I spend the most on?")["intent"] == "category_ranking"
    assert analyse(db, books, "Show me my unusual expenses this month.")["intent"] == "unusual_expenses"
    assert analyse(db, books, "Which merchant did I spend the most on?")["intent"] == "merchants"
    assert analyse(db, books, "How much did I spend in October?")["intent"] == "month_summary"


# ── the model reads, the code adds up ──────────────────────────────────────

def test_the_prompt_carries_the_composed_summary(db, books, scripted):
    conversation = models.Conversation(id="t285-conv", user_id=books.id, title="summary")
    db.add(conversation)
    db.commit()
    model = scripted({"reply": "November: income ₹90,000, expenses ₹16,150.56.", "actions": []})

    turn = graph.run_turn(db, books, conversation.id,
                          "Give me my financial health summary for this month.",
                          [], turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "financial_health_summary"
    prompt = model.last_system
    assert "financial_health_summary" in prompt
    assert "net_cash_flow" in prompt
    assert "16150.56" in prompt
    assert "big dinner" in prompt
