"""A validation error must never carry a secret back to the caller (Task 25.3, L2).

Pydantic quotes the offending input in ``detail[].input``; for a password, a token
or a secret that would put the value in the HTTP response and in any log that
records the body. The message and the location stay, so a client still learns what
failed and why.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import _redact
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
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


# ── end to end ───────────────────────────────────────────────────────────


def test_a_short_password_is_redacted(client):
    response = client.post("/api/auth/register", json={
        "name": "Test User", "email": "fresh@local.dev", "password": "s3cret!"})

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "password"]
    assert detail["input"] == "[redacted]"
    assert detail["msg"] == "String should have at least 8 characters"
    assert "s3cret!" not in response.text


def test_a_missing_field_does_not_leak_the_password_in_the_body(client):
    """A "field required" error quotes the whole body, password included."""
    response = client.post("/api/auth/register", json={
        "email": "fresh@local.dev", "password": "s3cret!"})

    assert response.status_code == 422
    assert "s3cret!" not in response.text
    echoed = response.json()["detail"][0]["input"]
    assert echoed == {"email": "fresh@local.dev", "password": "[redacted]"}


@pytest.mark.parametrize("password", [12345678, None, ["a", "b"]])
def test_a_mistyped_password_is_redacted(client, password):
    response = client.post("/api/auth/login", json={"email": "fresh@local.dev", "password": password})

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "[redacted]"
    assert str(password) not in response.text


def test_an_invalid_email_is_still_reported(client):
    response = client.post("/api/auth/login", json={"email": "not-an-email", "password": "longenough"})

    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "email"]
    assert detail["input"] == "not-an-email", "a non-secret value is still echoed"


def test_a_money_error_keeps_its_input(client):
    response = client.post("/api/transactions", json={
        "kind": "expense", "amount": "0.004", "category": "Groceries", "txn_date": "2026-11-13"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "0.004"


# ── the redactor itself ──────────────────────────────────────────────────


@pytest.mark.parametrize("loc", [
    ("body", "password"),
    ("body", "current_password"),
    ("body", "new_password"),
    ("body", "confirm_password"),
    ("body", "token"),
    ("body", "access_token"),
    ("body", "refresh_token"),
    ("body", "id_token"),
    ("body", "api_token"),
    ("body", "secret"),
    ("body", "client_secret"),
    ("body", "api_key"),
    ("body", "authorization"),
    ("body", "user", "password"),
    ["body", "credentials", "access_token"],
])
def test_every_secret_location_is_redacted(loc):
    errors = [{"loc": loc, "input": "the-secret", "msg": "invalid"}]
    assert _redact(errors)[0]["input"] == "[redacted]"


def test_a_mapping_input_is_scrubbed_recursively():
    errors = [{"loc": ("body", "name"), "msg": "Field required",
               "input": {"user": {"password": "shh", "name": "ok"}, "token": "t-1",
                         "rows": [{"api_key": "k-1"}]}}]

    scrubbed = _redact(errors)[0]["input"]

    assert scrubbed == {"user": {"password": "[redacted]", "name": "ok"},
                        "token": "[redacted]", "rows": [{"api_key": "[redacted]"}]}


def test_non_secret_errors_are_left_alone():
    errors = [
        {"loc": ("body", "amount"), "input": "10.005", "msg": "value_error"},
        {"loc": ("body", "month"), "input": "2026-1", "msg": "string_pattern_mismatch"},
        {"loc": ("body", "name"), "input": None, "msg": "missing"},
    ]
    assert _redact(errors) == errors
