"""Task 27.6.3.2 — credentials never enter long-term memory.

Every case drives a real write path (model action, API fallback, manual
endpoint) and checks three things: no row, no echo of the value, and the same
refusal whether the value is a password, a token or an AWS key. All secrets
below are synthetic.
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pytest

from app import models
from app.agent import graph, obs


TODAY = date(2026, 11, 13)


@pytest.fixture()
def client(db, user):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app
    from app.security import get_current_user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


def turn(db, user, conversation, scripted, message, fact):
    model = scripted({"reply": "Noted.", "actions": [{"op": "remember", "fact": fact}]})
    result = graph.run_turn(db, user, conversation.id, message, [], turn=1, today=TODAY)
    return result, model


def rows(db, user):
    return db.query(models.MemoryFact).filter_by(user_id=user.id).count()


def say(client, conversation, message):
    response = client.post(f"/api/chat/conversations/{conversation.id}/messages",
                           json={"message": message},
                           headers={"X-User-Timezone": "Asia/Kolkata"})
    assert response.status_code == 200, response.text
    return response.json()


# ── A. the model's action cannot store a credential ───────────────────────

@pytest.mark.parametrize("message,fact,secret,kind", [
    ("Remember that my wifi password is hunter2.", "my wifi password is hunter2",
     "hunter2", "a password"),
    ("Remember that my API key is sk-test-not-a-real-key-1234.",
     "my API key is sk-test-not-a-real-key-1234", "sk-test-not-a-real-key-1234", "an API key"),
    ("Remember that my access token is Bearer abc123def456ghi.",
     "my access token is Bearer abc123def456ghi", "abc123def456ghi", "an access token"),
    ("Remember that my locker PIN is 4321.", "my locker PIN is 4321", "4321", "a PIN"),
    ("Remember that the passphrase is correct horse battery staple.",
     "the passphrase is correct horse battery staple", "correct horse battery staple",
     "a password"),
    ("Remember that my AWS key is AKIAIOSFODNN7EXAMPLE.",
     "my AWS key is AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE", "an AWS access key"),
])
def test_a_credential_is_refused(db, user, conversation, scripted, message, fact, secret, kind):
    before = rows(db, user)
    result, _ = turn(db, user, conversation, scripted, message, fact)

    assert result["applied"] == []
    assert result["failed"] and result["failed"][0]["success"] is False
    assert rows(db, user) == before, "a credential must never become a row"
    assert kind in result["reply"], "the refusal names the kind"
    assert "can't store" in result["reply"]
    assert secret not in result["reply"]
    assert secret not in json.dumps(result["failed"])


def test_the_refusal_is_counted_without_the_value(db, user, conversation, scripted, caplog):
    caplog.set_level(logging.INFO, logger="nirvaah.agent")
    before = obs.metrics()["counters"].get("memory_credential_refused", 0)
    result, _ = turn(db, user, conversation, scripted, "Remember that my wifi password is hunter2.",
                     "my wifi password is hunter2")
    after = obs.metrics()["counters"].get("memory_credential_refused", 0)

    assert after == before + 1
    assert "hunter2" not in caplog.text
    assert "hunter2" not in result["reply"]
    events = [line for line in caplog.text.splitlines() if "memory_credential_refused" in line]
    assert events and all("hunter2" not in line for line in events)


# ── B. harmless memories still work ───────────────────────────────────────

@pytest.mark.parametrize("message,fact", [
    ("Remember that I prefer vegetarian meals.", "user prefers vegetarian meals"),
    ("Remember that my project uses PostgreSQL 16.", "project uses PostgreSQL 16"),
])
def test_a_harmless_fact_is_still_stored(db, user, conversation, scripted, message, fact):
    before = rows(db, user)
    result, _ = turn(db, user, conversation, scripted, message, fact)

    assert result["applied"] and result["applied"][0]["verified"] is True
    assert rows(db, user) == before + 1


@pytest.mark.parametrize("message,fact", [
    ("Remember that the source code review is on Friday.", "source code review on Friday"),
    ("Remember that the error code is 500.", "error code is 500"),
    ("Remember that the zip code is 560001.", "zip code 560001"),
    ("Remember that I use a password manager.", "user uses a password manager"),
])
def test_the_word_code_is_not_a_credential(db, user, conversation, scripted, message, fact):
    before = rows(db, user)
    result, _ = turn(db, user, conversation, scripted, message, fact)

    assert result["applied"], result["failed"]
    assert rows(db, user) == before + 1


# ── C. the API fallback (no model action) ─────────────────────────────────

def test_the_api_fallback_refuses_and_does_not_leak(db, user, conversation, client, scripted):
    before = rows(db, user)
    scripted({"reply": "Noted.", "actions": []})
    body = say(client, conversation, "Remember that my wifi password is hunter2.")

    assert rows(db, user) == before
    assert body["applied"] == []
    assert "can't store a password" in body["content"]
    assert "hunter2" not in json.dumps(body)
    assert body["failed"] and body["failed"][0]["success"] is False


def test_the_api_fallback_stores_harmless_facts(db, user, conversation, client, scripted):
    before = rows(db, user)
    scripted({"reply": "Noted.", "actions": []})
    body = say(client, conversation, "Remember that my project uses PostgreSQL 16.")

    assert rows(db, user) == before + 1
    assert [a["op"] for a in body["applied"] if a.get("op") == "remember"] == ["remember"]


# ── D. the manual endpoint uses the same guard ────────────────────────────

def test_the_manual_endpoint_refuses_credentials(db, user, client):
    before = rows(db, user)
    response = client.post("/api/chat/memories",
                           json={"fact": "my API key is sk-test-not-a-real-key-1234"})

    assert response.status_code == 400
    assert "can't store an API key" in response.json()["detail"]
    assert "sk-test-not-a-real-key-1234" not in response.text
    assert rows(db, user) == before


def test_the_manual_endpoint_stores_harmless_facts(db, user, client):
    before = rows(db, user)
    response = client.post("/api/chat/memories", json={"fact": "I prefer concise answers."})

    assert response.status_code == 200
    assert response.json()["fact"] == "I prefer concise answers."
    assert rows(db, user) == before + 1


def test_no_memory_row_ever_contains_the_secret(db, user, conversation, client, scripted):
    scripted({"reply": "Noted.", "actions": []})
    say(client, conversation, "Remember that my wifi password is hunter2.")
    say(client, conversation, "Remember that my AWS key is AKIAIOSFODNN7EXAMPLE.")

    stored = [m.fact for m in db.query(models.MemoryFact).filter_by(user_id=user.id).all()]
    assert all("hunter2" not in f and "AKIAIOSFODNN7EXAMPLE" not in f for f in stored)
    assert stored == []
