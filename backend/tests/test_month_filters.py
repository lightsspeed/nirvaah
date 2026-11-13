"""Month filters are half-open date ranges an index on (user_id, txn_date) can serve.

The boundaries are the point of the change: the 1st of the month is included, the
last day is included, and the first instant of the next month is not. A filter on
`to_char(txn_date, 'YYYY-MM')` could not use an index and silently matched nothing
for a malformed month, which is preserved here.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import main as api
from app import models


def _txn(db, user, when: date, amount: float = 100.0, kind: str = "expense"):
    row = models.Transaction(
        user_id=user.id, kind=kind, amount=amount, category="Test",
        description=f"on {when.isoformat()}", payment_method="UPI", txn_date=when,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def boundary_user(db):
    """Its own user, so the seeded fixtures cannot leak into month=all counts."""
    row = models.User(name="Boundaries", email="boundaries@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def boundary_rows(db, boundary_user):
    """February 28, March 1, mid-March, March 31, April 1 — the exact edges."""
    return [
        _txn(db, boundary_user, date(2026, 2, 28), 10.0),
        _txn(db, boundary_user, date(2026, 3, 1), 20.0),
        _txn(db, boundary_user, date(2026, 3, 15), 30.0),
        _txn(db, boundary_user, date(2026, 3, 31), 40.0),
        _txn(db, boundary_user, date(2026, 4, 1), 50.0),
    ]


# ── the helper ──────────────────────────────────────────────────────────────

def test_month_bounds_are_half_open():
    assert api.month_bounds("2026-03") == (date(2026, 3, 1), date(2026, 4, 1))
    assert api.month_bounds("2026-02") == (date(2026, 2, 1), date(2026, 3, 1))


def test_december_rolls_into_the_next_year():
    assert api.month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))


@pytest.mark.parametrize("value", ["2026-13", "2026-00", "2026-3", "2026", "", None, "all", "2026-3x"])
def test_malformed_months_have_no_bounds(value):
    assert api.month_bounds(value) is None


# ── transactions ────────────────────────────────────────────────────────────

def test_transactions_month_filter_includes_first_and_last_day(db, boundary_user, boundary_rows):
    rows = api.list_transactions("2026-03", None, None, None, None, None, db, boundary_user, date(2026, 3, 10))
    assert [r["txn_date"] for r in rows] == ["2026-03-31", "2026-03-15", "2026-03-01"]


def test_transactions_month_filter_excludes_the_next_month(db, boundary_user, boundary_rows):
    rows = api.list_transactions("2026-03", None, None, None, None, None, db, boundary_user, date(2026, 3, 10))
    assert "2026-04-01" not in [r["txn_date"] for r in rows]
    assert "2026-02-28" not in [r["txn_date"] for r in rows]


def test_transactions_month_filter_is_user_scoped(db, user, boundary_user, boundary_rows):
    _txn(db, user, date(2026, 3, 5), 999.0)          # the same month, a different user

    mine = api.list_transactions("2026-03", None, None, None, None, None, db, boundary_user, date(2026, 3, 10))
    theirs = api.list_transactions("2026-03", None, None, None, None, None, db, user, date(2026, 3, 10))

    assert [r["txn_date"] for r in mine] == ["2026-03-31", "2026-03-15", "2026-03-01"]
    assert [r["txn_date"] for r in theirs] == ["2026-03-05"]
    assert 999.0 not in [r["amount"] for r in mine]


def test_transactions_response_shape_and_order_are_unchanged(db, boundary_user, boundary_rows):
    rows = api.list_transactions("2026-03", None, None, None, None, None, db, boundary_user, date(2026, 3, 10))
    assert set(rows[0]) == {"id", "kind", "amount", "category", "description", "payment_method", "txn_date"}
    assert rows[0]["txn_date"] == "2026-03-31"
    assert [r["amount"] for r in rows] == [40.0, 30.0, 20.0]


def test_transactions_all_time_still_returns_every_month(db, boundary_user, boundary_rows):
    rows = api.list_transactions("all", None, None, None, None, None, db, boundary_user, date(2026, 3, 10))
    assert [r["txn_date"] for r in rows] == ["2026-04-01", "2026-03-31", "2026-03-15", "2026-03-01", "2026-02-28"]


def test_transactions_explicit_date_range_still_wins(db, boundary_user, boundary_rows):
    rows = api.list_transactions(None, "2026-03-10", "2026-03-20", None, None, None, db, boundary_user, date(2026, 3, 10))
    assert [r["txn_date"] for r in rows] == ["2026-03-15"]


def test_transactions_malformed_month_matches_nothing(db, boundary_user, boundary_rows):
    assert api.list_transactions("2026-3", None, None, None, None, None, db, boundary_user, date(2026, 3, 10)) == []
    assert api.list_transactions("2026-13", None, None, None, None, None, db, boundary_user, date(2026, 3, 10)) == []


# ── dashboard ───────────────────────────────────────────────────────────────

def test_dashboard_month_counts_the_same_rows(db, boundary_user, boundary_rows):
    payload = api.dashboard("2026-03", None, None, db, boundary_user, date(2026, 3, 10))
    assert payload["total_txns"] == 3
    assert payload["expenses"] == 90.0
    assert [t["txn_date"] for t in payload["recent_transactions"]] == ["2026-03-31", "2026-03-15", "2026-03-01"]
    assert payload["period"] == "2026-03"


def test_dashboard_default_month_uses_the_callers_today(db, boundary_user, boundary_rows):
    payload = api.dashboard(None, None, None, db, boundary_user, date(2026, 3, 10))
    assert payload["period"] == "2026-03"
    assert payload["total_txns"] == 3


def test_dashboard_all_time_is_unchanged(db, boundary_user, boundary_rows):
    payload = api.dashboard("all", None, None, db, boundary_user, date(2026, 3, 10))
    assert payload["total_txns"] == 5
    assert payload["period"] == "All Time"


# ── analytics range (same month semantics, from..to inclusive) ──────────────

def test_analytics_month_range_includes_both_ends_and_excludes_april(db, boundary_user, boundary_rows):
    payload = api.analytics("2026-02", "2026-03", None, None, db, boundary_user, date(2026, 3, 10))
    assert payload["total_txns"] == 4          # Feb 28 + the three March rows
    assert payload["total_expense"] == 100.0
    assert payload["from"] == "2026-02" and payload["to"] == "2026-03"


def test_analytics_single_month(db, boundary_user, boundary_rows):
    payload = api.analytics("2026-03", "2026-03", None, None, db, boundary_user, date(2026, 3, 10))
    assert payload["total_txns"] == 3
