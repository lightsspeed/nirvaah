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


# ── M1: exponents that used to overflow the decimal context ───────────────


@pytest.mark.parametrize("value", [
    "1e999999", "1e1000000", "1e999999999", "-1e999999999",
    Decimal("1E+999999999"), "-1E+1000000",
])
def test_extreme_exponents_are_money_errors(value):
    for call in (money.to_money, money.require_money, money.number):
        with pytest.raises(money.MoneyError):
            call(value)


def test_zero_with_a_huge_exponent_is_just_zero():
    assert money.to_money(Decimal("0E+999999999")) == Decimal("0.00")
    assert money.number(Decimal("0E+999999999")) == 0.0


def test_the_ceiling_still_behaves_after_the_exponent_guard():
    assert money.require_money("999999999999.99", positive=True) == money.MAX
    assert money.require_money("999999999999.994", positive=True) == money.MAX
    with pytest.raises(money.MoneyError):
        money.require_money("999999999999.995", positive=True)
    with pytest.raises(money.MoneyError):
        money.require_money("1000000000000", positive=True)


@pytest.mark.parametrize("value", ["1e1000000", "1e999999999", "-1e999999999"])
def test_api_answers_422_not_500_for_extreme_exponents(client, value):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": value, "category": "Groceries", "txn_date": "2026-11-13"})
    assert response.status_code == 422, f"{value!r} -> {response.status_code} {response.text[:120]}"


# ── M2: the journal's sign rule matches every other write ────────────────


def test_assistant_journal_rejects_a_negative_create(db, user):
    before = db.query(models.JournalEntry).count()
    result = execution.execute(db, user, {
        "op": "add_journal", "title": "negative", "amount": -5, "date": "2026-11-13"})

    assert result["success"] is False, result
    assert "negative" in (result["error"] or "")
    assert db.query(models.JournalEntry).count() == before


def test_assistant_journal_update_rejects_a_negative_amount(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "positive", "amount": 12.34, "date": "2026-11-13"})
    assert created["success"] is True

    result = execution.execute(db, user, {
        "op": "update_journal", "id": created["entity_id"], "amount": -1})

    assert result["success"] is False, result
    assert "negative" in (result["error"] or "")
    assert _journal(db, "positive").amount == Decimal("12.34")


def test_assistant_journal_normalises_a_negative_zero_amount(db, user):
    result = execution.execute(db, user, {
        "op": "add_journal", "title": "minus nothing", "amount": -0.004, "date": "2026-11-13"})

    assert result["success"] is True, result
    assert _journal(db, "minus nothing").amount == Decimal("0.00")
    assert json.dumps(result["changes"]["amount"]["after"]) == "0.0"


def test_assistant_journal_still_accepts_positive_amounts(db, user):
    created = execution.execute(db, user, {
        "op": "add_journal", "title": "positive", "amount": 2.675, "date": "2026-11-13"})
    updated = execution.execute(db, user, {
        "op": "update_journal", "id": created["entity_id"], "amount": 10.005})

    assert created["success"] is True and created["verified"] is True
    assert updated["success"] is True and updated["verified"] is True
    assert _journal(db, "positive").amount == Decimal("10.01")


# ── L3: zero has no sign ────────────────────────────────────────────────


def test_negative_zero_serialises_as_positive_zero():
    assert money.to_money("-0.00") == Decimal("0.00")
    assert str(money.to_money("-0.004")) == "0.00"
    assert money.number(Decimal("-0.00")) == 0.0
    assert json.dumps(money.number(Decimal("-0.00"))) == "0.0"
    assert json.dumps(money.json_numbers({"a": Decimal("-0.00")})) == '{"a": 0.0}'


# ── L4: integers are not money ──────────────────────────────────────────


def test_as_plain_keeps_integers_whole():
    from app.agent.fields import as_plain

    assert as_plain(5) == 5
    assert isinstance(as_plain(5), int) and not isinstance(as_plain(5), bool)
    assert as_plain(True) is True
    assert as_plain(None) is None
    assert as_plain("x") == "x"
    assert as_plain(Decimal("2.675")) == 2.68
    assert isinstance(as_plain(Decimal("2.675")), float)


# ── the four other financial writers follow their own rules ─────────────


NEGATIVE_CASES = [
    ("budget limit", {"op": "add_budget", "category": "X", "monthly_limit": -5, "month": "2026-11"},
     "Budget", "monthly_limit must be more than zero"),
    ("goal target", {"op": "add_goal", "name": "G", "target_amount": -100, "saved_amount": 0},
     "Goal", "target_amount must be more than zero"),
    ("goal saved", {"op": "add_goal", "name": "G", "target_amount": 100, "saved_amount": -10},
     "Goal", "saved_amount must not be negative"),
    ("investment invested", {"op": "add_investment", "name": "I", "asset_type": "mf",
                             "invested_amount": -5, "current_value": 0},
     "Investment", "invested_amount must not be negative"),
    ("investment current", {"op": "add_investment", "name": "I", "asset_type": "mf",
                            "invested_amount": 1000, "current_value": -6},
     "Investment", "current_value must not be negative"),
    ("liability outstanding", {"op": "add_liability", "name": "L", "liability_type": "loan",
                               "outstanding_amount": -5, "monthly_emi": 0},
     "Liability", "outstanding_amount must not be negative"),
    ("liability emi", {"op": "add_liability", "name": "L", "liability_type": "loan",
                       "outstanding_amount": 100, "monthly_emi": -6},
     "Liability", "monthly_emi must not be negative"),
]


@pytest.mark.parametrize("label,action,model_name,message", NEGATIVE_CASES,
                         ids=[case[0] for case in NEGATIVE_CASES])
def test_assistant_rejects_negative_amounts(db, user, label, action, model_name, message):
    model = getattr(models, model_name)
    before = db.query(model).count()

    result = execution.execute(db, user, action)

    assert result["success"] is False, f"{label}: {result}"
    assert result["error"] == message
    assert db.query(model).count() == before, f"{label} created a row anyway"


ZERO_CASES = [
    ("budget limit", {"op": "add_budget", "category": "X", "monthly_limit": 0, "month": "2026-11"},
     "Budget", False),
    ("goal target", {"op": "add_goal", "name": "G", "target_amount": 0, "saved_amount": 0},
     "Goal", False),
    ("goal saved", {"op": "add_goal", "name": "G", "target_amount": 100, "saved_amount": 0},
     "Goal", True),
    ("investment", {"op": "add_investment", "name": "I", "asset_type": "mf",
                    "invested_amount": 0, "current_value": 0}, "Investment", True),
    ("liability", {"op": "add_liability", "name": "L", "liability_type": "loan",
                   "outstanding_amount": 0, "monthly_emi": 0}, "Liability", True),
]


@pytest.mark.parametrize("label,action,model_name,accepted", ZERO_CASES,
                         ids=[case[0] for case in ZERO_CASES])
def test_zero_follows_each_field_rule(db, user, label, action, model_name, accepted):
    model = getattr(models, model_name)
    before = db.query(model).count()

    result = execution.execute(db, user, action)

    assert result["success"] is accepted, f"{label}: {result}"
    assert db.query(model).count() - before == (1 if accepted else 0)
    if not accepted:
        assert "more than zero" in (result["error"] or "")


ROUNDS_TO_ZERO_CASES = [
    ("budget limit", {"op": "add_budget", "category": "X", "monthly_limit": 0.004,
                      "month": "2026-11"}, "Budget", False, "monthly_limit"),
    ("goal target", {"op": "add_goal", "name": "G", "target_amount": 0.004, "saved_amount": 0},
     "Goal", False, "target_amount"),
    ("goal saved", {"op": "add_goal", "name": "G", "target_amount": 100, "saved_amount": 0.004},
     "Goal", True, "saved_amount"),
    ("investment invested", {"op": "add_investment", "name": "I", "asset_type": "mf",
                             "invested_amount": 0.004, "current_value": 0},
     "Investment", True, "invested_amount"),
    ("liability outstanding", {"op": "add_liability", "name": "L", "liability_type": "loan",
                               "outstanding_amount": 0.004, "monthly_emi": 0},
     "Liability", True, "outstanding_amount"),
]


@pytest.mark.parametrize("label,action,model_name,accepted,field", ROUNDS_TO_ZERO_CASES,
                         ids=[case[0] for case in ROUNDS_TO_ZERO_CASES])
def test_a_value_that_rounds_to_zero_follows_the_same_rule(db, user, label, action, model_name,
                                                           accepted, field):
    model = getattr(models, model_name)
    before = db.query(model).count()

    result = execution.execute(db, user, action)

    assert result["success"] is accepted, f"{label}: {result}"
    if accepted:
        stored = getattr(db.query(model).order_by(model.id.desc()).first(), field)
        assert stored == Decimal("0.00")
    else:
        assert db.query(model).count() == before


def test_optional_amounts_default_as_before(db, user):
    goal = execution.execute(db, user, {"op": "add_goal", "name": "G", "target_amount": 100})
    investment = execution.execute(db, user, {
        "op": "add_investment", "name": "I", "asset_type": "mf", "invested_amount": 1000})
    liability = execution.execute(db, user, {
        "op": "add_liability", "name": "L", "liability_type": "loan", "outstanding_amount": 100})

    assert goal["success"] is True and investment["success"] is True and liability["success"] is True
    assert db.query(models.Goal).filter_by(name="G").one().saved_amount == Decimal("0.00")
    assert db.query(models.Investment).filter_by(name="I").one().current_value == Decimal("1000.00")
    assert db.query(models.Liability).filter_by(name="L").one().monthly_emi == Decimal("0.00")


def test_a_required_amount_cannot_be_omitted(db, user):
    before = db.query(models.Budget).count()

    result = execution.execute(db, user, {"op": "add_budget", "category": "X", "month": "2026-11"})

    assert result["success"] is False
    assert "monthly_limit is required" in (result["error"] or "")
    assert db.query(models.Budget).count() == before


def test_valid_positive_amounts_still_verify(db, user):
    budget = execution.execute(db, user, {"op": "add_budget", "category": "X",
                                          "monthly_limit": 500.005, "month": "2026-11"})
    goal = execution.execute(db, user, {"op": "add_goal", "name": "G", "target_amount": 80000.555,
                                        "saved_amount": 0.005})
    investment = execution.execute(db, user, {"op": "add_investment", "name": "I", "asset_type": "mf",
                                              "invested_amount": 1000.004, "current_value": 1200.005})
    liability = execution.execute(db, user, {"op": "add_liability", "name": "L", "liability_type": "loan",
                                             "outstanding_amount": 250000.005, "monthly_emi": 3000.999})

    for result in (budget, goal, investment, liability):
        assert result["success"] is True, result
        assert result["verified"] is True, result
    assert db.query(models.Budget).filter_by(category="X").one().monthly_limit == Decimal("500.01")
    row = db.query(models.Goal).filter_by(name="G").one()
    assert (row.target_amount, row.saved_amount) == (Decimal("80000.56"), Decimal("0.01"))
    row = db.query(models.Investment).filter_by(name="I").one()
    assert (row.invested_amount, row.current_value) == (Decimal("1000.00"), Decimal("1200.01"))
    row = db.query(models.Liability).filter_by(name="L").one()
    assert (row.outstanding_amount, row.monthly_emi) == (Decimal("250000.01"), Decimal("3001.00"))


INVALID_UPDATE_CASES = [
    ("budget limit", {"op": "add_budget", "category": "B", "monthly_limit": 100, "month": "2026-11"},
     "update_budget", {"monthly_limit": -1}, "Budget", "monthly_limit", Decimal("100.00")),
    ("goal target", {"op": "add_goal", "name": "G", "target_amount": 100, "saved_amount": 0},
     "update_goal", {"target_amount": 0}, "Goal", "target_amount", Decimal("100.00")),
    ("goal saved", {"op": "add_goal", "name": "G2", "target_amount": 100, "saved_amount": 10},
     "update_goal", {"saved_amount": -1}, "Goal", "saved_amount", Decimal("10.00")),
    ("investment invested", {"op": "add_investment", "name": "I", "asset_type": "mf",
                             "invested_amount": 1000, "current_value": 1100},
     "update_investment", {"invested_amount": -1}, "Investment", "invested_amount",
     Decimal("1000.00")),
    ("liability emi", {"op": "add_liability", "name": "L", "liability_type": "loan",
                       "outstanding_amount": 100, "monthly_emi": 5},
     "update_liability", {"monthly_emi": -1}, "Liability", "monthly_emi", Decimal("5.00")),
]


@pytest.mark.parametrize("label,create,op,change,model_name,field,expected", INVALID_UPDATE_CASES,
                         ids=[case[0] for case in INVALID_UPDATE_CASES])
def test_an_invalid_update_leaves_the_record_alone(db, user, label, create, op, change,
                                                   model_name, field, expected):
    model = getattr(models, model_name)
    created = execution.execute(db, user, create)
    assert created["success"] is True, created
    row = db.query(model).filter_by(id=created["entity_id"]).one()

    result = execution.execute(db, user, {"op": op, "id": row.id, **change})
    db.refresh(row)

    assert result["success"] is False, f"{label}: {result}"
    assert getattr(row, field) == expected, f"{label} changed the stored value"
