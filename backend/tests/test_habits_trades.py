"""Habits and the trading journal: personal records, never money.

Both have their own tables and their own sync stamp. These tests pin the API
contract and — importantly — that neither leaks into the dashboard or analytics.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import models
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user


@pytest.fixture()
def account(db):
    row = models.User(name="Records", email="records@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture()
def client(db, account):
    def _db():
        try:
            yield db
        finally:
            pass

    fastapi_app.dependency_overrides[get_db] = _db
    fastapi_app.dependency_overrides[get_current_user] = lambda: account
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


def test_a_habit_keeps_clean_daily_checks(client):
    created = client.post("/api/habits", json={
        "id": "habit-1",
        "name": "Walk 30 minutes",
        "category": "Health",
        "target": 5,
        "checks": ["2026-11-26", "2026-11-25", "2026-11-25", "not-a-day"],
    })
    assert created.status_code == 200, created.text
    habit = created.json()
    assert habit["checks"] == ["2026-11-25", "2026-11-26"]
    assert habit["target"] == 5

    listed = client.get("/api/habits").json()
    assert [h["id"] for h in listed] == ["habit-1"]


def test_a_habit_target_is_clamped_and_delete_is_tombstoned(client):
    created = client.post("/api/habits", json={
        "id": "habit-2", "name": "Read", "target": 99, "checks": [],
    }).json()
    assert created["target"] == 7

    assert client.delete("/api/habits/habit-2").json() == {"ok": True}
    assert client.get("/api/habits").json() == []
    assert client.get("/api/deletions", params={"kind": "habits"}).json()[0]["id"] == "habit-2"


def test_a_trade_round_trips_and_updates_its_exit(client):
    created = client.post("/api/trades", json={
        "id": "trade-1",
        "trade_date": "2026-11-26",
        "symbol": "nifty",
        "side": "buy",
        "quantity": 50,
        "entry_price": 24000.5,
        "fees": 40,
        "setup": "Breakout",
        "notes": "First entry on the retest",
    })
    assert created.status_code == 200, created.text
    trade = created.json()
    assert trade["symbol"] == "NIFTY"
    assert trade["quantity"] == 50
    assert trade["entry_price"] == 24000.5
    assert trade["exit_price"] is None

    # The journal uses POST for upserts, like the other life records.
    updated = client.post("/api/trades", json={
        "id": "trade-1", "trade_date": "2026-11-26", "symbol": "NIFTY",
        "side": "buy", "quantity": 50, "entry_price": 24000.5,
        "exit_price": 24120, "fees": 40,
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["exit_price"] == 24120

    listed = client.get("/api/trades").json()
    assert [t["id"] for t in listed] == ["trade-1"]

    assert client.delete("/api/trades/trade-1").json() == {"ok": True}
    assert client.get("/api/trades").json() == []


def test_trade_validation_refuses_bad_input(client):
    base = {
        "id": "trade-bad", "trade_date": "2026-11-26", "symbol": "TCS",
        "side": "buy", "quantity": 1, "entry_price": 100,
    }
    assert client.post("/api/trades", json={**base, "side": "hold"}).status_code == 422
    assert client.post("/api/trades", json={**base, "quantity": 0}).status_code == 422
    assert client.post("/api/trades", json={**base, "symbol": ""}).status_code == 422
    assert client.post("/api/trades", json={**base, "entry_price": -1}).status_code == 422


def test_habits_and_trades_do_not_touch_money(client):
    client.post("/api/habits", json={"id": "habit-money", "name": "No spend day", "checks": ["2026-11-26"]})
    client.post("/api/trades", json={
        "id": "trade-money", "trade_date": "2026-11-26", "symbol": "BTC",
        "side": "sell", "quantity": 1, "entry_price": 100, "exit_price": 150, "fees": 0,
    })

    dashboard = client.get("/api/dashboard", params={"month": "2026-11"}).json()
    analytics = client.get("/api/analytics", params={"from": "2026-11", "to": "2026-11"}).json()

    assert dashboard["income"] == 0
    assert dashboard["expenses"] == 0
    assert dashboard["category_expenses"] == []
    assert analytics["total_income"] == 0
    assert analytics["total_expense"] == 0
    assert analytics["category_breakdown"] == []


def test_the_sync_fingerprint_notices_habit_and_trade_changes(client):
    before = client.get("/api/sync/version").json()["version"]

    client.post("/api/habits", json={"id": "habit-sync", "name": "Stretch", "checks": []})
    after_habit = client.get("/api/sync/version").json()["version"]
    assert after_habit != before

    client.post("/api/trades", json={
        "id": "trade-sync", "trade_date": "2026-11-26", "symbol": "INFY",
        "side": "buy", "quantity": 2, "entry_price": 100,
    })
    assert client.get("/api/sync/version").json()["version"] != after_habit
