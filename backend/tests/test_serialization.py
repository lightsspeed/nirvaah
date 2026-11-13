"""Timestamp serialization: instants carry an explicit UTC marker, days do not.

The database keeps naive UTC and the columns keep their types — this is purely the
boundary where values become JSON. A timestamp without a marker is read as local
wall time by every browser, which is exactly the class of bug this pins down.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user
from app.timeutil import iso_utc


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


# ── the helper ─────────────────────────────────────────────────────────────


def test_naive_datetime_is_serialized_as_utc():
    assert iso_utc(datetime(2026, 11, 13, 1, 36, 23, 123456)) == "2026-11-13T01:36:23.123456Z"


def test_aware_datetime_is_normalized_to_utc():
    ist = ZoneInfo("Asia/Kolkata")
    assert iso_utc(datetime(2026, 11, 13, 7, 6, 23, tzinfo=ist)) == "2026-11-13T01:36:23Z"
    assert iso_utc(datetime(2026, 11, 13, 1, 36, 23, tzinfo=ZoneInfo("UTC"))) == "2026-11-13T01:36:23Z"


def test_none_stays_none():
    assert iso_utc(None) is None


def test_serialized_value_parses_back_to_the_same_instant():
    original = datetime(2026, 11, 13, 1, 36, 23, 500000)
    parsed = datetime.fromisoformat(iso_utc(original))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    assert parsed.replace(tzinfo=None) == original


# ── API responses ──────────────────────────────────────────────────────────


def test_note_timestamps_carry_the_utc_marker(client, db):
    created = client.post("/api/notes", json={"title": "Serialization check", "body": "x"}).json()
    payload = client.get("/api/notes").json()[0]

    assert payload["createdAt"].endswith("Z")
    assert payload["updatedAt"].endswith("Z")
    assert payload["createdAt"] == created["createdAt"]
    # the stored value is still naive UTC, unchanged by serialization
    row = db.get(models.Note, payload["id"])
    assert row.created_at.tzinfo is None
    assert datetime.fromisoformat(payload["createdAt"]).replace(tzinfo=None) == row.created_at


def test_task_due_dates_stay_date_only(client):
    created = client.post(
        "/api/tasks",
        json={"id": "ser-task", "text": "Serialization task", "due": "2026-11-20", "priority": "medium"},
    ).json()
    assert created["due"] == "2026-11-20"
    assert created["due"].count("-") == 2 and "T" not in created["due"]
    assert created["createdAt"].endswith("Z")

    listed = [t for t in client.get("/api/tasks").json() if t["id"] == "ser-task"][0]
    assert listed["due"] == "2026-11-20"


def test_journal_event_date_is_date_only_and_timestamps_are_utc(client):
    created = client.post(
        "/api/journal",
        json={"id": "ser-journal", "title": "Serialization entry", "date": "2026-11-11", "mood": "good"},
    ).json()
    assert created["date"] == "2026-11-11"
    assert "T" not in created["date"]
    assert created["createdAt"].endswith("Z") and created["updatedAt"].endswith("Z")


def test_transaction_and_dashboard_dates_are_date_only(client):
    client.post(
        "/api/transactions",
        json={
            "kind": "expense",
            "amount": 42,
            "category": "Groceries",
            "payment_method": "UPI",
            "txn_date": "2026-11-12",
        },
    )
    rows = client.get("/api/transactions", headers={"X-User-Timezone": "Asia/Kolkata"}).json()
    row = [r for r in rows if r["amount"] == 42][0]
    assert row["txn_date"] == "2026-11-12"

    dashboard = client.get("/api/dashboard", headers={"X-User-Timezone": "Asia/Kolkata"}).json()
    assert all("T" not in t["txn_date"] for t in dashboard["recent_transactions"])


def test_assistant_conversation_timestamps_are_utc(client):
    conversation = client.post("/api/chat/conversations", json={}).json()
    for key in ("created_at", "updated_at"):
        assert conversation[key].endswith("Z"), (key, conversation[key])

    listed = client.get("/api/chat/conversations").json()
    assert listed[0]["created_at"].endswith("Z")


def test_null_timestamps_serialize_as_json_null():
    """Timestamps are NOT NULL columns, but the boundary must not invent a value."""
    payload = {"createdAt": iso_utc(None), "updatedAt": iso_utc(None)}
    assert json.loads(json.dumps(payload)) == {"createdAt": None, "updatedAt": None}


def test_response_shapes_are_unchanged(client):
    """Only the timestamp strings change — keys, counts and date fields do not."""
    client.post("/api/notes", json={"title": "Shape check"})
    note = client.get("/api/notes").json()[0]
    assert set(note) >= {
        "id",
        "title",
        "body",
        "category",
        "tags",
        "pinned",
        "archived",
        "createdAt",
        "updatedAt",
    }
    dashboard = client.get("/api/dashboard").json()
    assert {"period", "month", "recent_transactions", "budgets"} <= set(dashboard)
    txn = client.post(
        "/api/transactions",
        json={
            "kind": "income",
            "amount": 10,
            "category": "Salary",
            "payment_method": "SBI",
            "txn_date": "2026-11-01",
        },
    ).json()
    assert set(txn) == {"id", "kind", "amount", "category", "description", "payment_method", "txn_date"}
    assert isinstance(json.dumps(txn), str)  # still plain JSON, no custom encoder


def test_date_objects_never_gain_a_time_component():
    """A guard against someone routing `date` through the timestamp serializer."""
    assert date(2026, 12, 1).isoformat() == "2026-12-01"
    assert iso_utc(datetime(2026, 12, 1)) == "2026-12-01T00:00:00Z"
