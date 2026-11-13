"""Listing a filtered set of transactions, not just totalling it.

The reproduction case is the one that failed in production: 38 grocery
transactions in April 2026 totalling 7,897.00. The aggregate was answerable and
the records were not, because no intent returned rows. These tests pin the rows,
the count, the SQL total, the truncation metadata and the prompt budget.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import ai, models
from app.agent import planner
from app.agent.graph import _facts_block


TODAY = date(2026, 11, 13)
APRIL_TOTAL = Decimal("7897.00")


@pytest.fixture()
def april_groceries(db):
    """38 April grocery rows summing to 7,897.00, plus boundaries and noise."""
    user = models.User(name="Lister", email="lister@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)

    amounts = [Decimal("207.82")] * 37 + [APRIL_TOTAL - Decimal("207.82") * 37]
    for index, amount in enumerate(amounts):
        db.add(models.Transaction(
            user_id=user.id, kind="expense", amount=amount, category="Groceries",
            description=f"grocery run {index}", payment_method="SBI",
            txn_date=date(2026, 4, 1) + timedelta(days=index % 30),
        ))
    db.add(models.Transaction(
        user_id=user.id, kind="expense", amount=Decimal("500.00"), category="Groceries",
        description="may groceries", payment_method="HDFC", txn_date=date(2026, 5, 1),
    ))
    db.add(models.Transaction(
        user_id=user.id, kind="income", amount=Decimal("90000.00"), category="Salary",
        description="april salary", payment_method="SBI", txn_date=date(2026, 4, 1),
    ))
    db.add(models.Transaction(
        user_id=user.id, kind="expense", amount=Decimal("450.00"), category="Dining Out",
        description="restaurant dinner", payment_method="SBI", txn_date=date(2026, 4, 12),
    ))
    db.commit()
    return user


def analyse(db, user, message):
    return planner.analyse(db, user, message, today=TODAY)


def test_the_april_grocery_scenario(db, april_groceries):
    analysis = analyse(db, april_groceries, "List down the grocery spends of April.")

    assert analysis["intent"] == "list_transactions"
    facts = analysis["facts"]
    assert facts["status"] == "ok"
    assert facts["category"] == "Groceries"
    assert facts["month"] == "2026-04"
    assert facts["count"] == 38
    assert facts["total"] == 7897.0
    assert facts["shown"] == 38
    assert facts["truncated"] is False
    assert len(facts["transactions"]) == 38
    # The aggregate is authoritative: the rows add up to it, they do not define it.
    assert round(sum(row["amount"] for row in facts["transactions"]), 2) == facts["total"]
    assert all(row["date"].startswith("2026-04") for row in facts["transactions"])


def test_every_row_carries_the_five_asked_for_fields(db, april_groceries):
    facts = analyse(db, april_groceries, "List grocery spends in April.")["facts"]
    expected = {"date", "amount", "category", "description", "payment_method"}
    assert all(set(row) == expected for row in facts["transactions"])
    assert all(isinstance(row["amount"], (int, float)) for row in facts["transactions"])


@pytest.mark.parametrize("word", ["grocery", "groceries", "GROCERY", "Groceries"])
def test_singular_plural_and_case_all_match_the_category(db, april_groceries, word):
    analysis = analyse(db, april_groceries, f"Show my {word} transactions in April.")

    assert analysis["intent"] == "list_transactions"
    assert analysis["facts"]["category"] == "Groceries"
    assert analysis["facts"]["count"] == 38


@pytest.mark.parametrize("message,expected", [
    ("How much did I spend on groceries in April?", "category_month"),
    ("What is my average monthly grocery spending?", "category_series"),
    ("Which month had the highest grocery spending?", "category_series"),
    ("Show me the total spend on groceries in April.", "category_month"),
])
def test_aggregate_questions_keep_their_routing(db, april_groceries, message, expected):
    analysis = analyse(db, april_groceries, message)

    assert analysis["intent"] == expected
    assert "transactions" not in analysis["facts"]


@pytest.mark.parametrize("message", [
    "List grocery spends in April.",
    "Show all expenses from September.",
    "Display my restaurant transactions last month.",
    "Give me the details of grocery spending in April.",
    "Which transactions contributed to my April grocery spending?",
])
def test_listing_requests_reach_the_retrieval_intent(db, april_groceries, message):
    assert analyse(db, april_groceries, message)["intent"] == "list_transactions"


def test_month_boundaries_are_half_open(db, april_groceries):
    facts = analyse(db, april_groceries, "List grocery spends in April.")["facts"]
    dates = {row["date"] for row in facts["transactions"]}
    assert "2026-04-01" in dates          # first day is inside
    assert "2026-04-30" in dates          # last day is inside
    assert "2026-05-01" not in dates      # the next month is not


def test_rows_from_another_user_are_never_listed(db, april_groceries):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=Decimal("999.00"),
                              category="Groceries", description="not mine",
                              payment_method="SBI", txn_date=date(2026, 4, 10)))
    db.commit()

    facts = analyse(db, april_groceries, "List grocery spends in April.")["facts"]
    assert facts["count"] == 38
    assert all("not mine" not in row["description"] for row in facts["transactions"])


def test_retrieval_does_not_modify_the_ledger(db, april_groceries):
    before = db.query(models.Transaction).count()
    analyse(db, april_groceries, "List grocery spends in April.")
    db.expire_all()
    assert db.query(models.Transaction).count() == before


def test_truncation_is_reported_not_silent(db, april_groceries):
    for index in range(55):
        db.add(models.Transaction(
            user_id=april_groceries.id, kind="expense", amount=Decimal("10.00"),
            category="Groceries", description=f"june run {index}", payment_method="SBI",
            txn_date=date(2026, 6, 1) + timedelta(days=index % 28),
        ))
    db.commit()

    facts = analyse(db, april_groceries, "List grocery spends in June.")["facts"]
    assert facts["count"] == 55
    assert facts["shown"] == planner.LIST_LIMIT
    assert facts["truncated"] is True
    assert len(facts["transactions"]) == planner.LIST_LIMIT
    shown_total = round(sum(row["amount"] for row in facts["transactions"]), 2)
    assert shown_total < facts["total"] == 550.0


def test_the_facts_block_never_cuts_a_record_or_the_json(db, april_groceries):
    for index in range(150):
        db.add(models.Transaction(
            user_id=april_groceries.id, kind="expense", amount=Decimal("12.34"),
            category="Groceries", description=f"july run {index} at a fairly long shop name",
            payment_method="SBI", txn_date=date(2026, 7, 1) + timedelta(days=index % 28),
        ))
    db.commit()

    analysis = analyse(db, april_groceries, "List grocery spends in July.")
    block = _facts_block(analysis)

    assert len(block) <= 6000
    facts = json.loads(block.split("FACTS: ", 1)[1])
    assert facts["count"] == 150
    assert facts["truncated"] is True
    assert facts["shown"] == len(facts["transactions"]) < facts["count"]
    assert all(set(row) == {"date", "amount", "category", "description", "payment_method"}
               for row in facts["transactions"])


def test_the_april_block_is_within_budget(db, april_groceries):
    block = _facts_block(analyse(db, april_groceries, "List grocery spends in April."))
    assert len(block) <= 6000
    facts = json.loads(block.split("FACTS: ", 1)[1])
    assert facts["shown"] == 38 and facts["truncated"] is False


def test_an_empty_range_says_so_instead_of_zero(db, april_groceries):
    analysis = analyse(db, april_groceries, "List grocery spends in February.")
    assert analysis["intent"] == "list_transactions"
    assert analysis["facts"]["count"] == 0
    assert analysis["facts"]["transactions"] == []
    assert analysis["facts"]["status"] == "no_data_for_category"
    assert "STATUS: no_data_for_category" in _facts_block(analysis)


def test_income_listing_uses_the_income_side(db, april_groceries):
    facts = analyse(db, april_groceries, "List my income transactions in April.")["facts"]
    assert facts["kind"] == "income"
    assert [row["description"] for row in facts["transactions"]] == ["april salary"]


def test_the_prompt_says_how_to_present_rows():
    assert "one per line" in ai.SYSTEM_RULES
    assert "never add the rows up" in ai.SYSTEM_RULES
