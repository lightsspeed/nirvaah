"""Money at the boundaries: the assistant's journal path, and refusing huge input.

Two rules this pins down:

* an amount the assistant writes is quantised by the application, never by the
  database — SQLite would happily store 2.675 in a ``numeric(14,2)`` column, and
  PostgreSQL would round whatever the driver sent, which is not our policy;
* input that cannot be an amount is a 422, not a 500. ``decimal.InvalidOperation``
  used to escape ``quantize()`` and take the request down with it.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import models, money
from app.agent import execution
from app.database import get_db
from app.main import app as fastapi_app
from app.security import get_current_user


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
        yield TestClient(fastapi_app, raise_server_exceptions=False)
    finally:
        fastapi_app.dependency_overrides.clear()


def _journal(db, title):
    return db.query(models.JournalEntry).filter_by(title=title).one()


# ── the assistant's journal path ───────────────────────────────────────────


def test_assistant_journal_create_quantises_half_up(db, user):
    result = execution.execute(db, user, {
        "op": "add_journal", "title": "coffee", "amount": 2.675, "date": "2026-11-13"})

    assert result["success"] is True, result
    assert result["verified"] is True
    assert _journal(db, "coffee").amount == Decimal("2.68")
    assert result["changes"]["amount"]["after"] == 2.68


def test_assistant_journal_update_quantises_half_up(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "coffee", "amount": 1, "date": "2026-11-13"})
    assert created["success"] is True

    result = execution.execute(db, user, {
        "op": "update_journal", "id": created["entity_id"], "amount": 10.005})

    assert result["success"] is True, result
    assert result["verified"] is True
    assert _journal(db, "coffee").amount == Decimal("10.01")
    assert result["changes"]["amount"]["after"] == 10.01


def test_assistant_journal_keeps_a_null_amount(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "no money", "amount": None, "date": "2026-11-13"})

    assert created["success"] is True, created
    assert created["verified"] is True
    assert _journal(db, "no money").amount is None
    assert created["changes"]["amount"]["after"] is None


def test_assistant_journal_update_without_an_amount_leaves_it_alone(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "keep", "amount": 12.34, "date": "2026-11-13"})
    assert created["success"] is True

    result = execution.execute(db, user, {
        "op": "update_journal", "id": created["entity_id"], "title": "renamed"})

    assert result["success"] is True
    assert _journal(db, "renamed").amount == Decimal("12.34")


def test_a_persisted_journal_write_is_never_reported_as_failed(db, user):
    """The write that stores 2.68 must not be compared against round(2.675) = 2.67."""
    result = execution.execute(db, user, {
        "op": "add_journal", "title": "verified", "amount": 2.675, "date": "2026-11-13"})

    assert result["success"] is True, result
    assert result["verified"] is True, result
    assert result["error"] is None
    # the row really is there, which is what makes a false failure dangerous
    assert _journal(db, "verified") is not None


def test_assistant_changes_carry_json_numbers_not_strings(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "numbers", "amount": 2.675, "date": "2026-11-13"})
    updated = execution.execute(db, user, {
        "op": "update_journal", "id": created["entity_id"], "amount": 10.005})

    for result in (created, updated):
        change = result["changes"]["amount"]
        for side in ("before", "after"):
            value = change.get(side)
            assert value is None or isinstance(value, float), f"{side} was {value!r}"
        json.dumps(result)

    assert updated["changes"]["amount"] == {"before": 2.68, "after": 10.01}


def test_assistant_transaction_changes_are_numbers_too(db, user):
    result = execution.execute(db, user, {
        "op": "add_transaction", "kind": "expense", "amount": 10.005, "category": "Groceries",
        "description": "receipt", "txn_date": "2026-11-13"})

    assert result["success"] is True
    assert result["changes"]["amount"]["after"] == 10.01
    assert isinstance(result["changes"]["amount"]["after"], float)


def test_sqlite_does_not_enforce_the_numeric_scale(db, user):
    """The suite must not pretend the database is what rounds a 3-decimal amount.

    A raw float written around the application lands in a ``numeric(14,2)`` column
    untouched on SQLite, so quantisation has to live in the code — which is why the
    assistant path now calls ``money.to_money`` before it writes.
    """
    row = models.JournalEntry(id="raw-scale", user_id=user.id, title="raw", amount=2.675,
                              event_date=None)
    db.add(row)
    db.commit()

    stored, kind = db.execute(
        text("SELECT amount, typeof(amount) FROM journal_entries WHERE id='raw-scale'")).one()
    assert Decimal(str(stored)) == Decimal("2.675"), "SQLite keeps three decimals"
    assert kind == "real"
    # and the ORM's own conversion is not our rule: it reads the binary value back
    # as 2.67, a paisa away from the ROUND_HALF_UP answer
    assert row.amount == Decimal("2.67")
    assert money.to_money(2.675) == Decimal("2.68"), "our policy, applied before the write"


# ── invalid input is a 422 ────────────────────────────────────────────────


@pytest.mark.parametrize("value", [1e30, "1e30", "1e400", 1e13])
def test_out_of_range_amounts_are_rejected_not_crashed(client, value):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": value, "category": "Groceries", "txn_date": "2026-11-13"})
    assert response.status_code == 422, f"{value!r} -> {response.status_code} {response.text[:120]}"


@pytest.mark.parametrize("value", [1e30, "1e30", "1e400", 1e13])
def test_out_of_range_amounts_are_rejected_on_update(client, db, user, value):
    created = client.post("/api/transactions", json={
        "kind": "expense", "amount": 10, "category": "Groceries", "txn_date": "2026-11-13"})
    assert created.status_code == 200

    response = client.put(f"/api/transactions/{created.json()['id']}", json={
        "kind": "expense", "amount": value, "category": "Groceries", "txn_date": "2026-11-13"})
    assert response.status_code == 422


def test_non_finite_amounts_are_rejected(client):
    for body in ('{"kind":"expense","amount":NaN,"category":"Fresh","txn_date":"2026-11-13"}',
                 '{"kind":"expense","amount":Infinity,"category":"Fresh","txn_date":"2026-11-13"}',
                 '{"kind":"expense","amount":-Infinity,"category":"Fresh","txn_date":"2026-11-13"}'):
        response = client.post("/api/transactions", content=body,
                               headers={"content-type": "application/json"})
        assert response.status_code == 422, f"{body} -> {response.status_code}"


@pytest.mark.parametrize("path,body", [
    ("/api/budgets", {"category": "Food", "monthly_limit": 1e30, "month": "2026-11"}),
    ("/api/goals", {"name": "Trip", "target_amount": 1e30, "saved_amount": 0}),
    ("/api/investments", {"name": "Fund", "asset_type": "mf", "invested_amount": 1e30,
                          "current_value": 0}),
    ("/api/liabilities", {"name": "Loan", "liability_type": "loan", "outstanding_amount": 1e30,
                          "monthly_emi": 0}),
])
def test_every_monetary_schema_refuses_an_impossible_amount(client, path, body):
    assert client.post(path, json=body).status_code == 422


def test_the_maximum_amount_is_still_accepted(client):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": "999999999999.99", "category": "Groceries",
        "txn_date": "2026-11-13"})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == 999999999999.99


def test_a_value_that_rounds_into_range_is_accepted(client):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": "999999999999.994", "category": "Groceries",
        "txn_date": "2026-11-13"})
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == 999999999999.99


def test_the_helpers_raise_money_error_not_invalid_operation():
    from decimal import InvalidOperation

    for value in (1e30, "1e30", "1e400", Decimal("1E+30"), float("nan"), float("inf")):
        with pytest.raises(money.MoneyError):
            money.to_money(value)
        with pytest.raises(money.MoneyError):
            money.require_money(value, positive=True)
        with pytest.raises((money.MoneyError, InvalidOperation)) as caught:
            money.number(value)
        assert isinstance(caught.value, money.MoneyError), "number() is a read path: no raw decimal error"


def test_zero_after_quantisation_is_still_refused(client):
    for value in ("0.004", "0.001", 0, "-0.004"):
        response = client.post("/api/transactions", json={
            "kind": "expense", "amount": value, "category": "Groceries", "txn_date": "2026-11-13"})
        assert response.status_code == 422, f"{value!r} -> {response.status_code}"
