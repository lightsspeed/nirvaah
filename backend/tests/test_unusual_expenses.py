"""Task 28.4 — unusual expense detection: median + MAD, computed by the database layer.

Own ledger per test module (conftest's seed is deliberately thin in each
category, which is itself one of the cases under test).
"""

from __future__ import annotations

import statistics
from datetime import date
from decimal import Decimal

import pytest

from app import models
from app.agent import analytics, graph, planner


TODAY = date(2026, 11, 13)

LEDGER = [
    # Dining Out: eight rows in a tight band around ₹600, one ₹8,000 outlier
    ("expense", 520, "Dining Out", "cafe", date(2026, 5, 3)),
    ("expense", 560, "Dining Out", "cafe", date(2026, 5, 9)),
    ("expense", 600, "Dining Out", "cafe", date(2026, 6, 2)),
    ("expense", 620, "Dining Out", "cafe", date(2026, 6, 12)),
    ("expense", 640, "Dining Out", "cafe", date(2026, 6, 20)),
    ("expense", 600, "Dining Out", "cafe", date(2026, 7, 4)),
    ("expense", 580, "Dining Out", "cafe", date(2026, 8, 6)),
    ("expense", 610, "Dining Out", "cafe", date(2026, 9, 7)),
    ("expense", 8000, "Dining Out", "big dinner", date(2026, 11, 8)),
    # Groceries: six rows around ₹970, one ₹4,000 outlier in June
    ("expense", 900, "Groceries", "shop", date(2026, 5, 10)),
    ("expense", 950, "Groceries", "shop", date(2026, 6, 10)),
    ("expense", 980, "Groceries", "shop", date(2026, 7, 10)),
    ("expense", 1000, "Groceries", "shop", date(2026, 8, 10)),
    ("expense", 960, "Groceries", "shop", date(2026, 9, 10)),
    ("expense", 990, "Groceries", "shop", date(2026, 10, 10)),
    ("expense", 4000, "Groceries", "bulk", date(2026, 6, 28)),
    # Two rows only: not enough history to call anything unusual
    ("expense", 5000, "Gadgets", "tablet", date(2026, 11, 2)),
    ("expense", 6000, "Gadgets", "phone", date(2026, 11, 4)),
    # Income of the same magnitude must never be a candidate or a baseline
    ("income", 50000, "Dining Out", "refund", date(2026, 11, 9)),
]


@pytest.fixture()
def ledger(db):
    row = models.User(name="Ledger", email="ledger@local.dev", password_hash="x")
    db.add(row)
    db.commit()
    for kind, amount, category, description, when in LEDGER:
        db.add(models.Transaction(user_id=row.id, kind=kind, amount=amount, category=category,
                                  description=description, payment_method="UPI", txn_date=when))
    db.commit()
    return row


def anomalies(facts):
    return [(a["date"], a["category"], a["amount"], a["median"], a["ratio"]) for a in facts["anomalies"]]


def analyse(db, user, message, context=None, turn=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn)


# ── detection ──────────────────────────────────────────────────────────────

def test_a_genuinely_high_expense_is_detected(db, ledger):
    facts = analytics.unusual_expenses(db, ledger)

    assert facts["status"] == "ok"
    assert facts["count"] == 2
    top = facts["anomalies"][0]
    assert top["date"] == "2026-11-08"
    assert top["category"] == "Dining Out"
    assert top["description"] == "big dinner"
    assert top["amount"] == 8000.0
    assert top["median"] == 600.0
    assert top["difference"] == 7400.0
    assert top["ratio"] == 13.33
    assert top["z"] is not None and top["z"] > 3.5
    assert top["rule"] == "modified_z"


def test_ordinary_expenses_are_not_detected(db, ledger):
    facts = analytics.unusual_expenses(db, ledger)

    assert ("2026-06-02", "Dining Out", 600.0, ...) not in anomalies(facts)
    assert [a["amount"] for a in facts["anomalies"]] == [8000.0, 4000.0]


def test_the_candidate_is_excluded_from_its_own_baseline(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, category="Dining Out")
    top = facts["anomalies"][0]

    # Eight earlier dining rows; the ₹8,000 itself must not lift its baseline.
    assert top["history_count"] == 8
    assert top["median"] == 600.0


def test_evidence_matches_the_database(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, category="Dining Out")
    amounts = [Decimal(str(a)) for a, in db.query(models.Transaction.amount).filter(
        models.Transaction.user_id == ledger.id,
        models.Transaction.kind == "expense",
        models.Transaction.category == "Dining Out").all()]
    history = [value for value in amounts if value != Decimal("8000.00")]

    assert float(statistics.median(history)) == facts["anomalies"][0]["median"]
    assert float(statistics.median([abs(v - statistics.median(history)) for v in history])) == \
        facts["anomalies"][0]["mad"]


def test_income_is_never_a_candidate_or_a_baseline(db, ledger):
    facts = analytics.unusual_expenses(db, ledger)

    assert all(a["category"] != "Salary" for a in facts["anomalies"])
    assert 50000.0 not in [a["amount"] for a in facts["anomalies"]]
    # The ₹50,000 refund is in Dining Out: it must not move that baseline either.
    assert facts["anomalies"][0]["median"] == 600.0


def test_another_users_transactions_are_excluded(db, ledger):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    for amount in (700, 720, 690, 750, 710, 700):
        db.add(models.Transaction(user_id=other.id, kind="expense", amount=amount,
                                  category="Dining Out", description="theirs",
                                  payment_method="UPI", txn_date=date(2026, 6, 6)))
    db.add(models.Transaction(user_id=other.id, kind="expense", amount=99999, category="Groceries",
                              description="theirs", payment_method="UPI", txn_date=date(2026, 6, 7)))
    db.commit()

    facts = analytics.unusual_expenses(db, ledger)

    assert [a["amount"] for a in facts["anomalies"]] == [8000.0, 4000.0]
    assert facts["anomalies"][0]["median"] == 600.0, "their rows must not move the baseline"


def test_a_category_with_identical_amounts_falls_back_to_a_multiple_of_the_median(db):
    user = models.User(name="Flat", email="flat@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for day in range(1, 8):
        db.add(models.Transaction(user_id=user.id, kind="expense", amount=500,
                                  category="Fuel", description="pump",
                                  payment_method="UPI", txn_date=date(2026, 5, day)))
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=2000,
                              category="Fuel", description="big tank",
                              payment_method="UPI", txn_date=date(2026, 5, 20)))
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=600,
                              category="Fuel", description="small tank",
                              payment_method="UPI", txn_date=date(2026, 5, 21)))
    db.commit()

    facts = analytics.unusual_expenses(db, user)
    detected = {a["description"]: a for a in facts["anomalies"]}

    assert list(detected) == ["big tank"]
    assert detected["big tank"]["rule"] == "median_multiple"
    assert detected["big tank"]["ratio"] == 4.0


def test_insufficient_history_is_reported_not_guessed(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, category="Gadgets")

    assert facts["status"] == "insufficient_history"
    assert facts["anomalies"] == []
    assert facts["count"] == 0
    assert facts["categories_needing_history"] == ["Gadgets"]
    assert facts["min_history"] == 5


def test_an_empty_window_is_no_data(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, month="2026-03")

    assert facts["status"] == "no_data"
    assert facts["anomalies"] == []


def test_a_window_with_no_outliers_reports_none(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, month="2026-07")

    assert facts["status"] == "ok"
    assert facts["count"] == 0
    assert facts["anomalies"] == []
    assert facts["evaluated"] > 0


def test_month_and_year_windows(db, ledger):
    assert [a["amount"] for a in analytics.unusual_expenses(db, ledger, month="2026-11")["anomalies"]] \
        == [8000.0]
    assert [a["amount"] for a in analytics.unusual_expenses(db, ledger, month="2026-06")["anomalies"]] \
        == [4000.0]
    assert [a["amount"] for a in analytics.unusual_expenses(db, ledger, year=2026)["anomalies"]] \
        == [8000.0, 4000.0]


def test_limit_is_respected(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, limit=1)

    assert len(facts["anomalies"]) == 1
    assert facts["count"] == 1
    assert facts["anomalies"][0]["amount"] == 8000.0


def test_unknown_category_is_named(db, ledger):
    facts = analytics.unusual_expenses(db, ledger, category="Yachts")

    assert facts["status"] == "unknown_category"
    assert "Yachts" in facts["message"]


def test_a_named_amount_is_judged_by_the_same_rule(db, ledger):
    high = analytics.unusual_expenses(db, ledger, category="Dining Out",
                                     probe_amount=Decimal("8000"))["probe"]
    normal = analytics.unusual_expenses(db, ledger, category="Dining Out",
                                       probe_amount=Decimal("700"))["probe"]

    assert high["unusual"] is True
    assert high["ratio"] == 13.33
    assert high["median"] == 600.0
    assert high["history_count"] == 9, "the probe is not a row, so nothing is excluded"
    assert normal["unusual"] is False
    assert normal["ratio"] == 1.17


# ── routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Is this expense unusual?",
    "Show me my unusual expenses this month.",
    "Was my ₹8,000 dining expense unusually high?",
    "Which transactions were much higher than normal?",
    "Find unusually high transactions.",
])
def test_unusual_questions_reach_the_detector(db, ledger, message):
    analysis = analyse(db, ledger, message)

    assert analysis["intent"] == "unusual_expenses"
    assert analysis["facts"]["method"].startswith("median + MAD")


def test_the_scope_comes_from_the_message(db, ledger):
    month = analyse(db, ledger, "Show me my unusual expenses this month.")["facts"]
    year = analyse(db, ledger, "Any unusual expenses this year?")["facts"]

    assert month["scope"] == "2026-11"
    assert year["scope"] == "2026"


def test_a_carried_category_does_not_narrow_the_scan(db, ledger):
    prior = {"intent": "category_series", "category": "Groceries", "month": None,
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, ledger, "Show me my unusual expenses this month.", context=prior, turn=2)

    assert analysis["intent"] == "unusual_expenses"
    assert analysis["facts"]["category"] is None
    assert [a["category"] for a in analysis["facts"]["anomalies"]] == ["Dining Out"]


def test_an_explicit_category_is_respected(db, ledger):
    facts = analyse(db, ledger, "Any unusual groceries expenses?")["facts"]

    assert facts["category"] == "Groceries"
    assert {a["category"] for a in facts["anomalies"]} == {"Groceries"}


def test_a_named_amount_reaches_the_probe(db, ledger):
    facts = analyse(db, ledger, "Was my ₹8,000 dining expense unusually high?")["facts"]

    assert facts["probe"]["amount"] == 8000.0
    assert facts["probe"]["unusual"] is True
    assert facts["probe"]["category"] == "Dining Out"


def test_neighbouring_analytics_still_work(db, ledger):
    assert analyse(db, ledger, "Which category did I spend the most on?")["intent"] == "category_ranking"
    assert analyse(db, ledger, "Which merchant did I spend the most on?")["intent"] == "merchants"
    assert analyse(db, ledger, "How much did I spend on groceries?")["intent"] == "category_series"
    assert analyse(db, ledger, "Show me my latest transactions.")["intent"] == "list_transactions"


# ── the model explains, the code decides ───────────────────────────────────

def test_the_prompt_carries_the_evidence_and_not_a_verdict(db, ledger, scripted):
    conversation = models.Conversation(id="t284-conv", user_id=ledger.id, title="unusual")
    db.add(conversation)
    db.commit()
    model = scripted({"reply": "Yes — ₹8,000 is 13.33× your usual ₹600.", "actions": []})

    turn = graph.run_turn(db, ledger, conversation.id, "Show me my unusual expenses this month.",
                          [], turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "unusual_expenses"
    prompt = model.last_system
    assert "unusual_expenses" in prompt
    assert "big dinner" in prompt
    assert "13.33" in prompt
    assert "history_count" in prompt
