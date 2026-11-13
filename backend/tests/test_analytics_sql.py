"""The assistant's analytics stay arithmetically identical now that SQL sums them.

Every expectation here is written out by hand from the five rows in `ledger`, so a
regression in the grouping, the rounding or the range boundaries shows up as a
number that no longer matches the arithmetic.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import ai, models
from app.agent import analytics, planner


@pytest.fixture()
def ledger(db):
    """One user, five transactions, three months — including both edges."""
    user = models.User(name="Analytics", email="analytics@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    rows = [
        ("income", 1000.00, "Salary", "employer", "SBI", date(2026, 3, 1)),
        ("expense", 100.00, "Food", "cafe", "UPI", date(2026, 3, 1)),     # first day of March
        ("expense", 200.00, "Food", "cafe", "UPI", date(2026, 3, 31)),    # last day of March
        ("expense", 50.00, "Food", "cafe", "Cash", date(2026, 4, 1)),     # first day of April
        ("income", 500.00, "Salary", "employer", "SBI", date(2026, 4, 15)),
    ]
    for kind, amount, category, description, method, when in rows:
        db.add(models.Transaction(user_id=user.id, kind=kind, amount=amount, category=category,
                                  description=description, payment_method=method, txn_date=when))
    db.commit()
    return user


@pytest.fixture()
def empty_user(db):
    user = models.User(name="Empty", email="empty@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── monthly totals and income/expense separation ────────────────────────────

def test_summary_separates_income_and_expense(db, ledger):
    assert analytics.summary(db, ledger, "2026-03") == {
        "status": "ok", "month": "2026-03", "income": 1000.0, "expense": 300.0,
        "savings": 700.0, "savings_rate": 70.0, "count": 3,
    }


def test_month_boundaries_are_inclusive_and_exclusive(db, ledger):
    april = analytics.summary(db, ledger, "2026-04")
    assert april["income"] == 500.0 and april["expense"] == 50.0 and april["count"] == 2
    # 2026-04-01 belongs to April only; March sees the 1st and the 31st
    march = analytics.summary(db, ledger, "2026-03")
    assert march["count"] == 3


def test_monthly_series_totals_and_rates(db, ledger):
    series = analytics.monthly_series(db, ledger)
    assert series["status"] == "ok"
    assert [m["month"] for m in series["months"]] == ["2026-03", "2026-04"]
    march, april = series["months"]
    assert (march["income"], march["expense"], march["savings"], march["savings_rate"], march["count"]) == \
        (1000.0, 300.0, 700.0, 70.0, 3)
    assert (april["income"], april["expense"], april["savings"], april["savings_rate"], april["count"]) == \
        (500.0, 50.0, 450.0, 90.0, 2)
    assert series["available_range"] == {"first": "2026-03", "last": "2026-04"}


def test_monthly_series_window_and_year(db, ledger):
    assert [m["month"] for m in analytics.monthly_series(db, ledger, months=1)["months"]] == ["2026-04"]
    assert len(analytics.monthly_series(db, ledger, year=2026)["months"]) == 2
    assert analytics.monthly_series(db, ledger, year=2001)["status"] == "no_data"


def test_extremes_and_comparison(db, ledger):
    extremes = analytics.extremes(db, ledger)
    assert extremes["highest_expense_month"] == {"month": "2026-03", "total": 300.0}
    assert extremes["lowest_expense_month"] == {"month": "2026-04", "total": 50.0}
    assert extremes["highest_income_month"] == {"month": "2026-03", "total": 1000.0}

    compare = analytics.compare_months(db, ledger, "2026-03", "2026-04")
    assert compare["expense_delta"] == -250.0
    assert compare["income_delta"] == -500.0
    assert compare["expense_change_pct"] == -83.3


# ── categories ──────────────────────────────────────────────────────────────

def test_categories_and_matching(db, ledger):
    assert analytics.categories(db, ledger) == ["Food", "Salary"]
    assert analytics.match_categories(db, ledger, "food") == ["Food"]
    assert analytics.match_categories(db, ledger, "Yachts") == []


def test_category_month_breakdown_and_months(db, ledger):
    facts = analytics.category_month(db, ledger, "Food", "2026-03")
    assert facts["status"] == "ok"
    assert facts["total"] == 300.0 and facts["count"] == 2
    assert facts["breakdown"] == [{"category": "Food", "total": 300.0, "count": 2}]
    assert facts["months_with_category"] == ["2026-03", "2026-04"]


def test_category_month_with_no_rows_in_the_month(db, ledger):
    facts = analytics.category_month(db, ledger, "Food", "2026-05")
    assert facts["status"] == "no_data_for_category"
    assert facts["breakdown"] == [{"category": "Food", "total": 0.0, "count": 0}]
    assert facts["months_with_category"] == ["2026-03", "2026-04"]


def test_category_month_unknown(db, ledger):
    facts = analytics.category_month(db, ledger, "Yachts", "2026-03")
    assert facts["status"] == "unknown_category"
    assert facts["known_categories"] == ["Food", "Salary"]


def test_category_series(db, ledger):
    series = analytics.category_series(db, ledger, "Food")
    assert series["series"] == [
        {"month": "2026-03", "total": 300.0, "count": 2},
        {"month": "2026-04", "total": 50.0, "count": 1},
    ]
    assert series["total"] == 350.0 and series["months"] == 2 and series["average"] == 175.0
    assert series["max_month"]["month"] == "2026-03" and series["min_month"]["month"] == "2026-04"


def test_category_by_month_shares(db, ledger):
    facts = analytics.category_by_month(db, ledger, "2026-03")
    assert facts["total"] == 300.0
    assert facts["categories"] == [{"category": "Food", "total": 300.0, "share_pct": 100.0}]
    assert facts["highest"] == facts["lowest"] == facts["categories"][0]


def test_multiple_categories_are_summed_separately(db, ledger):
    db.add(models.Transaction(user_id=ledger.id, kind="expense", amount=25.5, category="Travel",
                             description="train", payment_method="UPI", txn_date=date(2026, 3, 15)))
    db.commit()
    facts = analytics.category_by_month(db, ledger, "2026-03")
    assert facts["total"] == 325.5
    assert {c["category"]: c["total"] for c in facts["categories"]} == {"Food": 300.0, "Travel": 25.5}
    assert facts["categories"][0]["category"] == "Food"
    assert round(facts["categories"][1]["share_pct"], 1) == 7.8


# ── transaction-level answers ───────────────────────────────────────────────

@pytest.fixture()
def merchant_ledger(db):
    """One user, May and April, merchants spread across four categories."""
    user = models.User(name="Merchants", email="merchants@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    rows = [
        ("expense", 900.00, "Groceries", "BigBasket", "UPI", date(2026, 5, 3)),
        ("expense", 600.00, "Groceries", "More Supermarket", "UPI", date(2026, 5, 9)),
        ("expense", 1500.00, "Fuel", "HP Petrol", "SBI", date(2026, 5, 5)),
        ("expense", 800.00, "Dining Out", "Pizza Hut", "SBI", date(2026, 5, 7)),
        ("expense", 1200.00, "Electricity", "BESCOM", "SBI", date(2026, 5, 11)),
        ("expense", 700.00, "Groceries", "BigBasket", "UPI", date(2026, 4, 20)),
        ("income", 5000.00, "Salary", "Employer", "SBI", date(2026, 5, 1)),
    ]
    for kind, amount, category, description, method, when in rows:
        db.add(models.Transaction(user_id=user.id, kind=kind, amount=amount, category=category,
                                  description=description, payment_method=method, txn_date=when))
    db.commit()
    return user


def test_merchants_without_a_category_are_unchanged(db, merchant_ledger):
    facts = analytics.merchants(db, merchant_ledger, "2026-05")

    assert [(m["merchant"], m["total"]) for m in facts["merchants"]] == [
        ("HP Petrol", 1500.0),
        ("BESCOM", 1200.0),
        ("BigBasket", 900.0),
        ("Pizza Hut", 800.0),
        ("More Supermarket", 600.0),
    ]
    assert facts["scope"] == "all categories"
    assert facts["category"] is None


def test_merchants_filtered_by_category_exclude_other_categories(db, merchant_ledger):
    facts = analytics.merchants(db, merchant_ledger, "2026-05", category="Groceries")

    assert [(m["merchant"], m["total"]) for m in facts["merchants"]] == [
        ("BigBasket", 900.0),
        ("More Supermarket", 600.0),
    ]
    assert {m["category"] for m in facts["merchants"]} == {"Groceries"}
    assert facts["scope"] == "Groceries"
    assert facts["category"] == "Groceries"


def test_merchants_category_and_month_filter_together(db, merchant_ledger):
    may = analytics.merchants(db, merchant_ledger, "2026-05", category="Groceries")
    everything = analytics.merchants(db, merchant_ledger, category="Groceries")

    assert [m["total"] for m in may["merchants"]] == [900.0, 600.0]
    assert [(m["merchant"], m["total"]) for m in everything["merchants"]] == [
        ("BigBasket", 1600.0),
        ("More Supermarket", 600.0),
    ]
    assert everything["month"] is None


def test_merchants_category_matching_normalises_the_name(db, merchant_ledger):
    canonical = analytics.merchants(db, merchant_ledger, "2026-05", category="Groceries")
    for spelling in ("groceries", "GROCERIES", "Groceries "):
        facts = analytics.merchants(db, merchant_ledger, "2026-05", category=spelling)
        assert facts["merchants"] == canonical["merchants"]
        assert facts["scope"] == "Groceries"


def test_merchants_category_respects_the_kind(db, merchant_ledger):
    income = analytics.merchants(db, merchant_ledger, "2026-05", category="Salary", kind="income")
    expense = analytics.merchants(db, merchant_ledger, "2026-05", category="Salary")

    assert [(m["merchant"], m["total"]) for m in income["merchants"]] == [("Employer", 5000.0)]
    assert expense["status"] == "no_data"
    assert expense["scope"] == "Salary"


def test_merchants_unknown_category_is_reported_not_empty(db, merchant_ledger):
    facts = analytics.merchants(db, merchant_ledger, "2026-05", category="Yachts")

    assert facts["status"] == "unknown_category"
    assert "Groceries" in facts["known_categories"]
    assert "merchants" not in facts
    # An unknown category is not an all-category answer.
    assert facts["scope"] is None
    assert facts["requested_category"] == "Yachts"


def test_merchants_spanning_categories_are_not_labelled_with_one(db, merchant_ledger):
    user = merchant_ledger
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=300.00, category="Groceries",
                              description="Amazon", payment_method="UPI", txn_date=date(2026, 5, 20)))
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=700.00, category="Clothes",
                              description="Amazon", payment_method="UPI", txn_date=date(2026, 5, 21)))
    db.commit()

    everything = analytics.merchants(db, user, "2026-05")
    amazon = next(m for m in everything["merchants"] if m["merchant"] == "Amazon")

    assert amazon["total"] == 1000.0
    assert amazon["categories"] == ["Clothes", "Groceries"]   # by spend, not by age
    assert "category" not in amazon, "an all-category total is not one category"

    groceries = analytics.merchants(db, user, "2026-05", category="Groceries")
    filtered = next(m for m in groceries["merchants"] if m["merchant"] == "Amazon")
    assert filtered["total"] == 300.0
    assert filtered["category"] == "Groceries"
    assert "categories" not in filtered


def test_merchants_empty_category_month_is_safe(db, merchant_ledger):
    facts = analytics.merchants(db, merchant_ledger, "2019-01", category="Groceries")

    assert facts == {"status": "no_data", "month": "2019-01",
                     "category": "Groceries", "scope": "Groceries"}


def test_merchants_category_keeps_ordering_and_limit(db, merchant_ledger):
    facts = analytics.merchants(db, merchant_ledger, "2026-05", limit=2, category="Groceries")

    assert [m["merchant"] for m in facts["merchants"]] == ["BigBasket", "More Supermarket"]
    assert [m["total"] for m in facts["merchants"]] == sorted(
        [m["total"] for m in facts["merchants"]], reverse=True)


def test_merchants_category_stays_inside_the_user(db, merchant_ledger):
    other = models.User(name="Other", email="other-merchant@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=9999.00, category="Groceries",
                              description="NotMine", payment_method="UPI", txn_date=date(2026, 5, 15)))
    db.commit()

    facts = analytics.merchants(db, merchant_ledger, "2026-05", category="Groceries")

    assert "NotMine" not in {m["merchant"] for m in facts["merchants"]}


def test_merchants_and_frequency(db, ledger):
    facts = analytics.merchants(db, ledger)
    assert facts["merchants"] == [
        {"merchant": "cafe", "total": 350.0, "count": 3, "categories": ["Food"]},
    ]
    assert facts["most_frequent"][0]["merchant"] == "cafe"


def test_merchant_empty_and_month_scoped(db, ledger):
    assert analytics.merchants(db, ledger, "2019-01")["status"] == "no_data"
    assert analytics.merchants(db, ledger, "2026-04")["merchants"][0]["total"] == 50.0


def test_recurring_requires_min_months(db, ledger):
    assert analytics.recurring(db, ledger)["recurring"] == []          # only two months
    facts = analytics.recurring(db, ledger, min_months=2)
    assert facts["recurring"] == [{"merchant": "cafe", "months_seen": 2,
                                   "average": 116.67, "last_month": "2026-04"}]


def test_highest_transactions(db, ledger):
    facts = analytics.highest_transactions(db, ledger)
    assert [i["amount"] for i in facts["items"]] == [200.0, 100.0, 50.0]
    assert analytics.highest_transactions(db, ledger, month="2026-04")["items"][0]["amount"] == 50.0
    assert analytics.highest_transactions(db, ledger, kind="income")["items"][0]["amount"] == 1000.0
    assert analytics.highest_transactions(db, ledger, month="2019-01")["status"] == "no_data"


def test_search_filters_and_page(db, ledger):
    month = analytics.search(db, ledger, month="2026-03")
    assert month["count"] == 3 and month["total"] == 1300.0
    assert [t["date"] for t in month["transactions"]] == ["2026-03-31", "2026-03-01", "2026-03-01"]
    assert month["status"] == "ok"

    text = analytics.search(db, ledger, text="cafe", month="2026-04")
    assert text["count"] == 1 and text["total"] == 50.0

    paid = analytics.search(db, ledger, payment_method="cash")
    assert paid["count"] == 1 and paid["transactions"][0]["paid_with"] == "Cash"

    assert analytics.search(db, ledger, month="2019-01")["status"] == "no_data_for_category"
    assert analytics.search(db, ledger)["count"] == 5


def test_text_exists_is_a_literal_match(db, ledger):
    assert analytics.text_exists(db, ledger, "cafe") is True
    assert analytics.text_exists(db, ledger, "CAFE") is True
    assert analytics.text_exists(db, ledger, "zzz") is False
    assert analytics.text_exists(db, ledger, "   ") is False
    db.add(models.Transaction(user_id=ledger.id, kind="expense", amount=1.0, category="Cashback",
                             description="100% back", payment_method="UPI", txn_date=date(2026, 3, 2)))
    db.commit()
    assert analytics.text_exists(db, ledger, "100%") is True      # literal, not a wildcard
    assert analytics.text_exists(db, ledger, "%") is True
    assert analytics.text_exists(db, ledger, "0%") is True


def test_available_range(db, ledger):
    assert analytics.available_range(db, ledger) == {
        "status": "ok", "first_month": "2026-03", "last_month": "2026-04",
        "months": 2, "transactions": 5,
    }
    assert planner.available_range(db, ledger) == analytics.available_range(db, ledger)


# ── user isolation and the empty ledger ─────────────────────────────────────

def test_other_users_rows_do_not_leak(db, ledger):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.refresh(other)
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=999.0, category="Food",
                              description="cafe", payment_method="UPI", txn_date=date(2026, 3, 5)))
    db.commit()

    assert analytics.summary(db, ledger, "2026-03")["expense"] == 300.0
    assert analytics.monthly_series(db, ledger)["months"][0]["expense"] == 300.0
    assert analytics.merchants(db, ledger)["merchants"][0]["total"] == 350.0
    assert analytics.search(db, ledger, text="cafe")["count"] == 3
    assert analytics.available_range(db, ledger)["transactions"] == 5
    assert analytics.categories(db, ledger) == ["Food", "Salary"]

    assert analytics.summary(db, other, "2026-03")["expense"] == 999.0
    assert analytics.categories(db, other) == ["Food"]


def test_empty_ledger_answers(db, empty_user):
    assert analytics.categories(db, empty_user) == []
    assert analytics.text_exists(db, empty_user, "anything") is False
    assert analytics.monthly_series(db, empty_user) == {"status": "no_data"}
    assert analytics.extremes(db, empty_user) == {"status": "no_data"}
    assert analytics.merchants(db, empty_user) == {
        "status": "no_data", "month": None, "category": None, "scope": "all categories",
    }
    assert analytics.recurring(db, empty_user) == {"status": "no_data"}
    assert analytics.category_by_month(db, empty_user, "2026-03") == {"status": "no_data", "month": "2026-03"}
    assert analytics.highest_transactions(db, empty_user) == {"status": "no_data", "month": None}
    assert analytics.available_range(db, empty_user) == {"status": "no_data"}
    assert analytics.category_series(db, empty_user, "Food")["status"] == "unknown_category"
    assert analytics.summary(db, empty_user, "2026-03") == {
        "status": "ok", "month": "2026-03", "income": 0, "expense": 0,
        "savings": 0, "savings_rate": None, "count": 0,
    }


# ── the snapshot that feeds the prompt ─────────────────────────────────────

def test_snapshot_totals_match_the_ledger(db, ledger):
    snapshot = ai.build_snapshot(db, ledger, "2026-03", today=date(2026, 3, 15))
    assert snapshot["totals"]["this_month"] == {
        "income": 1000.0, "expense": 300.0, "savings": 700.0, "savings_rate": 70.0,
    }
    assert snapshot["totals"]["all_time"]["expense"] == 350.0
    assert snapshot["totals"]["transaction_count"] == 5
    assert snapshot["monthly_trend"] == [
        {"month": "2026-03", "income": 1000.0, "expense": 300.0, "savings": 700.0},
        {"month": "2026-04", "income": 500.0, "expense": 50.0, "savings": 450.0},
    ]
    assert snapshot["recent_transactions"][0]["date"] == "2026-04-15"
    assert len(snapshot["recent_transactions"]) == 5
    # categories the user spends on are always listed, even at zero this month
    assert {"category": "Food", "spent": 300.0} in snapshot["spend_by_category_this_month"]
