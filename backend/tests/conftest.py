"""Fixtures for the assistant reliability tests.

A throwaway SQLite database per test, a seeded user with a known few months of
transactions and tasks, and a scripted model. Nothing here touches ./finance.db,
the container's Postgres, or any real user's data.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_finance.db")

from app import models  # noqa: E402
from app.database import Base  # noqa: E402


@dataclass
class FakeReply:
    """What providers.ask() returns, in miniature."""
    text: str
    provider: str = "cloud"
    model: str = "deepseek-flash"
    degraded: str = ""
    note: str = ""


class ScriptedModel:
    """A model that says exactly what the test tells it to, in order.

    Each entry is the JSON body to return. When the script runs dry the last
    entry repeats, which is what makes retry behaviour observable.
    """

    def __init__(self, *responses):
        self.responses = [r if isinstance(r, str) else json.dumps(r) for r in responses]
        self.calls: list[list[dict]] = []
        self.index = 0

    def __call__(self, messages, validate=None, prefer=""):
        self.calls.append(messages)
        payload = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        if validate is not None:
            validate(payload)
        return FakeReply(text=payload)

    # helpers for assertions
    @property
    def system_prompts(self) -> list[str]:
        return [m[0]["content"] for m in self.calls if m and m[0]["role"] == "system"]

    @property
    def last_system(self) -> str:
        return self.system_prompts[-1] if self.calls else ""


def _seed(db, user):
    rows = [
        # June 2026 — the month the user asks about
        ("expense", 1444.62, "Dining Out", "Pizza Dinner", date(2026, 6, 4)),
        ("expense", 700.00, "Dining Out", "Pizza Dinner", date(2026, 6, 18)),
        ("expense", 900.00, "Groceries", "BigBasket", date(2026, 6, 9)),
        ("income", 90000.00, "Salary", "June salary", date(2026, 6, 1)),
        # May 2026 — office eats peak
        ("expense", 2867.00, "Office Eats", "Cafeteria", date(2026, 5, 12)),
        # August 2026 — a bigger office eats month, no June office eats
        ("expense", 1200.00, "Office Eats", "Cafeteria", date(2026, 8, 7)),
        # November 2026 — the current month
        ("expense", 350.00, "Dining Out", "Pizza Dinner", date(2026, 11, 10)),
        ("income", 88000.00, "Salary", "November salary", date(2026, 11, 1)),
    ]
    for kind, amount, category, description, when in rows:
        db.add(models.Transaction(user_id=user.id, kind=kind, amount=amount, category=category,
                                  description=description, payment_method="UPI", txn_date=when))
    for text, due in (("Wheel Balancing", date(2026, 11, 15)),
                      ("Creta Servicing", date(2026, 11, 15)),
                      ("Scooty Servicing", date(2026, 11, 15))):
        db.add(models.Task(id=f"seed-{text.replace(' ', '-').lower()}", user_id=user.id, text=text,
                           due=due, priority="medium", category="Personal"))
    db.add(models.JournalEntry(id="seed-journal-leave", user_id=user.id, title="Leave office at 7 PM",
                               description="Left on time", event_date=date(2026, 11, 11)))
    db.commit()


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user(db):
    row = models.User(name="Test User", email="test@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    db.refresh(row)
    _seed(db, row)
    return row


@pytest.fixture()
def conversation(db, user):
    row = models.Conversation(id="conv-test", user_id=user.id, title="Test")
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def scripted(monkeypatch):
    """Install a scripted model and return a setter you call with responses."""
    import app.agent.providers as providers

    def install(*responses):
        model = ScriptedModel(*responses)
        monkeypatch.setattr(providers, "ask", model)
        return model

    return install
