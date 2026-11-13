"""Business dates belong to the caller's timezone, not the server's UTC clock.

Deterministic by construction: every test freezes ``timeutil._utc_now``, so the
suite never depends on the real date. The through-line is *whose* day it is —
storage stays naive UTC and only calendar-date defaults change.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import models, timeutil
from app.agent import execution, fields, months, planner
from app.ai import build_snapshot
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user
from app.tz import user_today


IST = "Asia/Kolkata"
LA = "America/Los_Angeles"


@pytest.fixture()
def freeze(monkeypatch):
    """Point the one clock seam at a fixed instant."""

    def _freeze(iso_utc: str):
        fixed = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        monkeypatch.setattr(timeutil, "_utc_now", lambda: fixed)
        return fixed

    return _freeze


# ── the helper ──────────────────────────────────────────────────────────────


def test_kolkata_midnight_rollover(freeze):
    """00:30 IST on 1 Dec is still 30 Nov in UTC — the original bug."""
    freeze("2026-11-30T19:00:00Z")
    assert timeutil.today_for_timezone(IST) == date(2026, 12, 1)
    assert timeutil.today_for_timezone("UTC") == date(2026, 11, 30)


def test_kolkata_0529_and_0531(freeze):
    """Either side of the 05:30 IST boundary: both are the 1st to the user."""
    freeze("2026-11-30T23:59:00Z")  # 05:29 IST — UTC still says 30 Nov
    assert timeutil.today_for_timezone(IST) == date(2026, 12, 1)
    freeze("2026-12-01T00:01:00Z")  # 05:31 IST — UTC has caught up
    assert timeutil.today_for_timezone(IST) == date(2026, 12, 1)


def test_utc_timezone(freeze):
    freeze("2026-11-30T19:00:00Z")
    assert timeutil.today_for_timezone("UTC") == date(2026, 11, 30)


def test_negative_offset_timezone(freeze):
    """Los Angeles is behind UTC, so the 1st UTC is still the 30th there."""
    freeze("2026-12-01T03:00:00Z")  # 30 Nov 19:00 PST
    assert timeutil.today_for_timezone(LA) == date(2026, 11, 30)


def test_invalid_identifier_is_reported_not_silently_utc(freeze, caplog):
    freeze("2026-11-30T19:00:00Z")
    timeutil._warned.clear()
    with caplog.at_level(logging.WARNING, logger="nirvaah.time"):
        assert timeutil.today_for_timezone("Mars/Olympus") == date(2026, 11, 30)
    assert any("unknown timezone" in record.message for record in caplog.records)


def test_missing_identifier_is_utc(freeze):
    freeze("2026-11-30T19:00:00Z")
    assert timeutil.today_for_timezone(None) == date(2026, 11, 30)
    assert timeutil.today_for_timezone("") == date(2026, 11, 30)


def test_resolve_timezone_accepts_names_and_rejects_junk():
    assert timeutil.resolve_timezone(IST) is not None
    assert timeutil.resolve_timezone("  Asia/Kolkata  ") is not None
    assert timeutil.resolve_timezone("") is None
    assert timeutil.resolve_timezone(None) is None
    assert timeutil.resolve_timezone("Not/AZone") is None
    assert timeutil.resolve_timezone("x" * 200) is None


def test_browser_legacy_names_resolve(freeze):
    """Chrome reports Asia/Calcutta, which Debian 13's tzdata no longer links."""
    assert timeutil.resolve_timezone("Asia/Calcutta") is not None
    assert timeutil.resolve_timezone("US/Pacific") is not None
    assert timeutil.resolve_timezone("Europe/Kiev") is not None
    freeze("2026-11-30T19:00:00Z")
    assert timeutil.today_for_timezone("Asia/Calcutta") == date(2026, 12, 1)
    assert user_today("Asia/Calcutta") == date(2026, 12, 1)  # no 400 for a real browser


# ── the dependency ─────────────────────────────────────────────────────────


def test_dependency_rejects_an_invalid_header(freeze):
    freeze("2026-11-30T19:00:00Z")
    with pytest.raises(HTTPException) as caught:
        user_today("Mars/Olympus")
    assert caught.value.status_code == 400
    assert "Asia/Kolkata" in caught.value.detail


def test_dependency_without_header_is_utc(freeze):
    freeze("2026-11-30T19:00:00Z")
    assert user_today(None) == date(2026, 11, 30)
    assert user_today("Asia/Kolkata") == date(2026, 12, 1)


# ── HTTP endpoints ─────────────────────────────────────────────────────────


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


def test_dashboard_default_month_follows_the_timezone(db, user, client, freeze):
    row = models.Transaction(
        user_id=user.id, kind="expense", amount=100.0, category="Groceries", txn_date=date(2026, 12, 1)
    )
    db.add(row)
    db.commit()
    freeze("2026-11-30T19:00:00Z")  # 1 Dec 00:30 IST

    kolkata = client.get("/api/dashboard", headers={"X-User-Timezone": IST}).json()
    assert kolkata["period"] == "2026-12"
    assert row.id in [t["id"] for t in kolkata["recent_transactions"]]

    utc = client.get("/api/dashboard").json()
    assert utc["period"] == "2026-11"
    assert row.id not in [t["id"] for t in utc["recent_transactions"]]


def test_transactions_and_analytics_default_month(db, user, client, freeze):
    row = models.Transaction(
        user_id=user.id, kind="expense", amount=250.0, category="Fuel", txn_date=date(2026, 12, 1)
    )
    db.add(row)
    db.commit()
    freeze("2026-11-30T19:00:00Z")

    headers = {"X-User-Timezone": IST}
    rows = client.get("/api/transactions", headers=headers).json()
    assert [r["id"] for r in rows] == [row.id]

    report = client.get("/api/analytics", headers=headers).json()
    assert report["from"] == "2026-12" and report["to"] == "2026-12"

    cash = client.get("/api/cashflow?months=1", headers=headers).json()
    assert cash[-1]["month"] == "2026-12"


def test_invalid_header_is_a_400_not_a_silent_utc(client, freeze):
    freeze("2026-11-30T19:00:00Z")
    response = client.get("/api/dashboard", headers={"X-User-Timezone": "Mars/Olympus"})
    assert response.status_code == 400
    assert "Unknown timezone" in response.json()["detail"]


def test_missing_header_keeps_the_old_utc_answer(client, freeze):
    freeze("2026-11-30T19:00:00Z")
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json()["period"] == "2026-11"


# ── assistant paths ────────────────────────────────────────────────────────


def test_snapshot_uses_the_supplied_today(db, user):
    snapshot = build_snapshot(db, user, today=date(2026, 12, 1))
    assert snapshot["today"] == "2026-12-01"
    assert snapshot["month_in_focus"] == "2026-12"


def test_assistant_transaction_and_journal_default_to_the_callers_day(db, user):
    context = {"today": date(2026, 12, 1)}

    txn = execution.execute(
        db,
        user,
        {"op": "add_transaction", "kind": "expense", "amount": 90, "category": "Groceries"},
        context=context,
    )
    assert txn["success"] and txn["verified"]
    stored = db.get(models.Transaction, txn["entity_id"])
    assert stored.txn_date == date(2026, 12, 1)

    journal = execution.execute(db, user, {"op": "add_journal", "title": "Late night walk"}, context=context)
    assert journal["success"] and journal["verified"]
    entry = db.get(models.JournalEntry, journal["entity_id"])
    assert entry.event_date == date(2026, 12, 1)


def test_explicit_dates_ignore_the_timezone_context(db, user):
    txn = execution.execute(
        db,
        user,
        {
            "op": "add_transaction",
            "kind": "expense",
            "amount": 40,
            "category": "Fuel",
            "txn_date": "2026-01-15",
        },
        context={"today": date(2026, 12, 1)},
    )
    assert db.get(models.Transaction, txn["entity_id"]).txn_date == date(2026, 1, 15)

    journal = execution.execute(
        db,
        user,
        {"op": "add_journal", "title": "Old note", "date": "2026-02-03"},
        context={"today": date(2026, 12, 1)},
    )
    assert db.get(models.JournalEntry, journal["entity_id"]).event_date == date(2026, 2, 3)

    budget = execution.execute(
        db,
        user,
        {"op": "add_budget", "category": "Fuel", "monthly_limit": 3000, "month": "2026-03"},
        context={"today": date(2026, 12, 1)},
    )
    assert db.get(models.Budget, budget["entity_id"]).month == "2026-03"


def test_budget_and_month_fields_default_to_the_callers_day(db, user):
    budget = execution.execute(
        db,
        user,
        {"op": "add_budget", "category": "Fuel", "monthly_limit": 5000},
        context={"today": date(2026, 12, 1)},
    )
    assert db.get(models.Budget, budget["entity_id"]).month == "2026-12"

    assert fields.month({}, today=date(2026, 12, 1)) == "2026-12"
    assert fields.month({"month": "2026-04"}, today=date(2026, 12, 1)) == "2026-04"


def test_assistant_month_phrases_use_the_context():
    december_first = date(2026, 12, 1)
    assert months.resolve_focus_month("this month", today=december_first) == "2026-12"
    assert months.resolve_focus_month("last month", today=december_first) == "2026-11"
    assert planner.resolve_month("this month", today=december_first) == "2026-12"
    assert planner.resolve_month("last month", today=december_first) == "2026-11"


# ── model default removal ─────────────────────────────────────────────────


def test_transaction_now_requires_an_explicit_date(db, user):
    """The server no longer invents a UTC day for a transaction."""
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=10.0, category="Misc"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
