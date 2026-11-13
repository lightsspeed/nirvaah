"""Exact money: numeric(14,2) in the database, Decimal in Python, numbers in JSON.

Every amount the app stores is paise. The database refuses more precision, the
Python side quantises with ROUND_HALF_UP before it gets there, and the API keeps
sending JSON numbers so the frontend needs no change.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import models, money
from app.agent import analytics, execution
from app.database import get_db
from app.main import app as fastapi_app
from app.schemas import BudgetIn, GoalIn, InvestmentIn, LiabilityIn, TransactionIn
from app.security import get_current_user


@pytest.fixture()
def empty_user(db):
    """A user with no seeded transactions, for exact-total assertions."""
    row = models.User(name="Money Only", email="money@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def client(db, user):
    def _db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


# ── rounding ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("10.005", "10.01"),   # binary floats round this down; money rounds half up
        (2.675, "2.68"),
        (1.005, "1.01"),
        ("0.004", "0.00"),
        (0.005, "0.01"),
        ("0.015", "0.02"),
        (450, "450.00"),
        (Decimal("12.344"), "12.34"),
        (Decimal("12.345"), "12.35"),
        ("-3.335", "-3.34"),
    ],
)
def test_values_are_quantised_half_up(value, expected):
    assert money.to_money(value) == Decimal(expected)
    assert str(money.to_money(value)) == expected


def test_quantisation_has_exactly_two_decimals():
    assert money.to_money("7") == Decimal("7.00")
    assert money.to_money(7).as_tuple().exponent == -2


def test_totals_stay_exact():
    assert money.total([Decimal("0.10")] * 3) == Decimal("0.30")
    assert money.total([Decimal("10.01"), Decimal("0.01"), Decimal("0.01")]) == Decimal("10.03")
    assert money.total([]) == money.ZERO
    assert isinstance(money.total([Decimal("1.00")]), Decimal)


# ── acceptance and rejection ───────────────────────────────────────────────


@pytest.mark.parametrize("value", ["0.004", 0.001, 0, "0", 0.0, "-5", -0.001])
def test_amounts_that_round_to_zero_are_rejected(value):
    with pytest.raises(money.MoneyError):
        money.require_money(value, field="amount", positive=True)


def test_the_ceiling_is_numeric_14_2():
    assert money.MAX == Decimal("999999999999.99")
    assert money.to_money("999999999999.99") == money.MAX
    assert money.require_money("999999999999.99", positive=True) == money.MAX
    for too_big in ["1000000000000", "1000000000000.00", "9999999999999.99", 1e13]:
        with pytest.raises(money.MoneyError):
            money.require_money(too_big, positive=True)
    # reading is not writing: a sum of stored amounts may pass the ceiling
    assert money.total([money.MAX, money.MAX]) == Decimal("1999999999999.98")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, False, "abc", [], {}])
def test_non_amounts_are_rejected(value):
    with pytest.raises(money.MoneyError):
        money.to_money(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_absent_value_is_none_not_zero(value):
    assert money.to_money(value) is None
    assert money.to_money(value, default=money.ZERO) == money.ZERO


def test_negative_amounts_are_rejected():
    with pytest.raises(money.MoneyError):
        money.require_money(-1, positive=True)
    with pytest.raises(money.MoneyError):
        money.require_money(-1)          # no money column is negative in this app
    assert money.to_money(-1) == Decimal("-1.00")   # still a valid number


# ── JSON boundary ──────────────────────────────────────────────────────────


def test_json_numbers_converts_decimals_and_leaves_none():
    payload = {"amount": Decimal("10.00"), "rows": [{"limit": Decimal("250.50")}], "note": "x", "none": None}
    out = money.json_numbers(payload)
    assert out == {"amount": 10.0, "rows": [{"limit": 250.5}], "note": "x", "none": None}
    assert isinstance(out["amount"], float)
    assert json.dumps(out) == '{"amount": 10.0, "rows": [{"limit": 250.5}], "note": "x", "none": null}'


def test_number_keeps_null_nullable():
    assert money.number(None) is None
    assert money.number(Decimal("1.50")) == 1.5
    assert money.number("1.505") == 1.51


# ── request schemas ────────────────────────────────────────────────────────


def test_transaction_schema_quantises_at_the_edge():
    txn = TransactionIn(kind="expense", amount="10.005", category="Groceries", txn_date="2026-11-13")
    assert txn.amount == Decimal("10.01")
    assert txn.model_dump()["amount"] == Decimal("10.01")


@pytest.mark.parametrize("amount", ["0.004", 0, "-2", "1e13", "nan", "inf", "not money"])
def test_transaction_schema_rejects_unusable_amounts(amount):
    with pytest.raises(ValidationError):
        TransactionIn(kind="expense", amount=amount, category="Groceries", txn_date="2026-11-13")


def test_other_money_schemas_quantise():
    assert BudgetIn(category="Food", monthly_limit="500.005", month="2026-11").monthly_limit == Decimal("500.01")
    goal = GoalIn(name="Laptop", target_amount="80000", saved_amount="0.005", target_date=None)
    assert (goal.target_amount, goal.saved_amount) == (Decimal("80000.00"), Decimal("0.01"))
    assert InvestmentIn(name="Fund", asset_type="mf", invested_amount="1000.555",
                        current_value="1200.004").current_value == Decimal("1200.00")
    assert LiabilityIn(name="Car", liability_type="loan", outstanding_amount="100000",
                       monthly_emi="3000.999").monthly_emi == Decimal("3001.00")
    with pytest.raises(ValidationError):
        GoalIn(name="x", target_amount="0.001", saved_amount="0", target_date=None)


# ── API responses stay numeric ────────────────────────────────────────────


def test_api_money_fields_are_json_numbers(client, db, user):
    body = {"kind": "expense", "amount": 10.005, "category": "Groceries",
            "description": "half a paisa over", "payment_method": "SBI", "txn_date": "2026-11-13"}
    created = client.post("/api/transactions", json=body)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["amount"] == 10.01
    assert isinstance(payload["amount"], float), "money must not be a string"

    listed = client.get("/api/transactions")
    assert listed.status_code == 200
    assert listed.json()[0]["amount"] == 10.01
    assert '"amount":10.01' in listed.text.replace(" ", "")

    stored = db.query(models.Transaction).filter_by(id=payload["id"]).one()
    assert isinstance(stored.amount, Decimal)
    assert stored.amount == Decimal("10.01")


def test_api_rejects_a_transaction_worth_nothing(client):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": 0.004, "category": "Groceries", "txn_date": "2026-11-13"})
    assert response.status_code == 422


def test_dashboard_and_analytics_are_numbers(client, db, user):
    for value in ("1000.01", "0.01", "749.98"):
        created = client.post("/api/transactions", json={"kind": "expense", "amount": value,
                                                        "category": "Food", "txn_date": "2027-03-05"})
        assert created.status_code == 200, created.text
    dashboard = client.get("/api/dashboard", params={"month": "2027-03"}).json()
    assert dashboard["expenses"] == 1750.0
    assert isinstance(dashboard["expenses"], float)
    # /api/analytics filters by date range, not by month name
    analytics_body = client.get("/api/analytics", params={
        "start_date": "2027-03-01", "end_date": "2027-03-31"}).json()
    assert isinstance(analytics_body["total_expense"], float)
    assert json.loads(json.dumps(analytics_body))["total_expense"] == 1750.0


# ── journal: nullable money ───────────────────────────────────────────────


def test_journal_amount_is_nullable_and_quantised(client):
    blank = client.post("/api/journal", json={"title": "no money", "mood": "steady",
                                              "date": "2026-11-13", "amount": None})
    assert blank.status_code == 200, blank.text
    assert blank.json()["amount"] is None

    rounded = client.post("/api/journal", json={"title": "spent", "mood": "steady",
                                               "date": "2026-11-13", "amount": "12.345"})
    assert rounded.status_code == 200, rounded.text
    assert rounded.json()["amount"] == 12.35
    assert isinstance(rounded.json()["amount"], float)


def test_journal_refuses_an_amount_the_column_cannot_hold(client):
    bad = client.post("/api/journal", json={"title": "x", "date": "2026-11-13",
                                            "amount": "10000000000000"})
    assert bad.status_code == 422
    assert client.get("/api/journal").status_code == 200


def test_journal_row_keeps_a_null_amount(db, user):
    row = models.JournalEntry(id="money-journal-null", user_id=user.id, title="t", amount=None,
                              event_date=date(2026, 11, 13))
    db.add(row)
    db.commit()
    assert row.amount is None
    assert money.number(row.amount) is None


# ── AI snapshot ───────────────────────────────────────────────────────────


def _seed_money(db, user):
    db.add_all([
        models.Transaction(user_id=user.id, kind="income", amount=Decimal("5000.00"),
                           category="Salary", payment_method="SBI", txn_date=date(2026, 11, 1)),
        models.Transaction(user_id=user.id, kind="expense", amount=Decimal("1234.56"),
                           category="Rent", payment_method="SBI", txn_date=date(2026, 11, 2)),
        models.Budget(user_id=user.id, category="Rent", monthly_limit=Decimal("1500.00"), month="2026-11"),
        models.Goal(user_id=user.id, name="Laptop", target_amount=Decimal("80000.00"),
                    saved_amount=Decimal("12500.50"), target_date=None),
        models.Investment(user_id=user.id, name="Index fund", asset_type="mf",
                          invested_amount=Decimal("10000.00"), current_value=Decimal("11234.56"), notes=""),
        models.Liability(user_id=user.id, name="Car loan", liability_type="loan",
                         outstanding_amount=Decimal("250000.00"), monthly_emi=Decimal("7500.25"), notes=""),
        models.JournalEntry(id="money-journal", user_id=user.id, title="note", amount=Decimal("99.99"),
                            event_date=date(2026, 11, 3)),
    ])
    db.commit()


def test_snapshot_serialises_without_a_default_handler(db, empty_user):
    from app.ai import build_snapshot

    _seed_money(db, empty_user)
    snapshot = build_snapshot(db, empty_user, "2026-11")

    # json.dumps() with no default= is the real test: one Decimal and this raises.
    text = json.dumps(snapshot)
    assert "Decimal" not in text

    assert snapshot["totals"]["all_time"]["income"] == 5000.0
    assert snapshot["totals"]["all_time"]["expense"] == 1234.56
    assert isinstance(snapshot["net_worth"]["net_worth"], float)
    assert snapshot["net_worth"]["monthly_emi_total"] == 7500.25
    assert isinstance(snapshot["recent_transactions"][0]["amount"], float)
    assert snapshot["journal"][0]["amount"] == 99.99

    money_values = [snapshot["totals"]["all_time"]["income"], snapshot["net_worth"]["net_worth"],
                    snapshot["budgets"][0]["limit"], snapshot["goals"][0]["target"],
                    snapshot["investments"][0]["gain"], snapshot["liabilities"][0]["emi"]]
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in money_values)


def test_snapshot_with_no_activity_is_zero_not_null(db, empty_user):
    from app.ai import build_snapshot

    snapshot = build_snapshot(db, empty_user, "2026-11")
    assert snapshot["totals"]["all_time"] == {"income": 0.0, "expense": 0.0, "savings": 0.0, "savings_rate": 0}
    assert snapshot["net_worth"]["net_worth"] == 0.0
    json.dumps(snapshot)


def test_assistant_analytics_money_is_numeric(db, empty_user):
    _seed_money(db, empty_user)

    summary = analytics.summary(db, empty_user, month="2026-11")
    assert summary["income"] == 5000.0
    assert summary["expense"] == 1234.56
    assert summary["savings"] == 3765.44
    assert isinstance(summary["savings"], float)
    json.dumps(summary)

    series = analytics.monthly_series(db, empty_user, months=12, year=2026)
    assert series["months"][0]["expense"] == 1234.56
    assert isinstance(series["months"][0]["expense"], float)
    json.dumps(series)

    categories = analytics.category_by_month(db, empty_user, "2026-11")
    assert categories["total"] == 1234.56
    json.dumps(categories)


# ── assistant write and read paths ────────────────────────────────────────


def test_assistant_write_quantises_and_verifies(db, user):
    outcome = execution.execute(db, user, {
        "op": "add_transaction", "kind": "expense", "amount": "10.005",
        "category": "Groceries", "description": "assistant", "txn_date": "2026-11-13",
    })
    assert outcome["success"] is True, outcome
    row = db.query(models.Transaction).filter_by(description="assistant").one()
    assert row.amount == Decimal("10.01")
    assert isinstance(row.amount, Decimal)


def test_assistant_refuses_an_amount_that_rounds_to_zero(db, user):
    before = db.query(models.Transaction).count()
    outcome = execution.execute(db, user, {
        "op": "add_transaction", "kind": "expense", "amount": "0.004",
        "category": "Groceries", "txn_date": "2026-11-13",
    })
    assert outcome["success"] is False
    assert "zero" in (outcome["error"] or "").lower()
    assert db.query(models.Transaction).count() == before


def test_assistant_read_path_uses_exact_comparison():
    assert execution._same(Decimal("10.01"), 10.01) is True
    assert execution._same(Decimal("10.01"), 10) is False
    assert execution._same(Decimal("0.01"), 0.01) is True
    assert execution._same("10.01", Decimal("10.01")) is True
    assert execution._same(None, None) is True
    # both sides quantise to paise first, so sub-paise noise is not a difference
    assert execution._same(Decimal("10.01"), 10.0100001) is True
    assert execution._same(Decimal("10.01"), "10.016") is False
