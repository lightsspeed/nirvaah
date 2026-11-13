"""Task 29.3 — completion timestamps, completion history and progress.

Today is Friday 13 November 2026. Completion timestamps are written as explicit
UTC values so every period boundary is pinned rather than clock-dependent.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import models
from app.agent import execution, graph, planner
from app.agent import tasks as task_intel
from app.main import _apply_task
from app.timeutil import utcnow


TODAY = date(2026, 11, 13)
IST = "Asia/Kolkata"


@pytest.fixture()
def history(db):
    """One user with completions spread across the periods, plus open work."""
    user = models.User(name="Hist", email="hist@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    rows = [
        # id, text, done, completed_at, due
        ("c-today", "Completed this morning", True, datetime(2026, 11, 13, 4, 30), None),
        ("c-yesterday", "Completed yesterday", True, datetime(2026, 11, 12, 10, 0), None),
        ("c-week", "Completed Monday", True, datetime(2026, 11, 9, 6, 0), None),
        ("c-old", "Completed last month", True, datetime(2026, 10, 4, 6, 0), None),
        ("c-legacy", "Completed before the column existed", True, None, None),
        ("p-overdue", "Overdue thing", False, None, TODAY - timedelta(days=3)),
        ("p-later", "Due next week", False, None, TODAY + timedelta(days=7)),
        ("p-undated", "Someday maybe", False, None, None),
    ]
    for task_id, text, done, completed, due in rows:
        db.add(models.Task(id=task_id, user_id=user.id, text=text, done=done, due=due,
                           priority="medium", category="Personal", completed_at=completed,
                           created_at=datetime(2026, 10, 1)))
    db.commit()
    return user


def names(facts):
    return [task["text"] for task in facts["tasks"]]


def analyse(db, user, message, context=None, turn=None, timezone_name=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn,
                           timezone_name=timezone_name)


# ── lifecycle ──────────────────────────────────────────────────────────────

def test_completing_a_task_stamps_utc(db):
    user = models.User(name="L", email="l@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    created = execution.execute(db, user, {"op": "add_task", "text": "Ship the report"})
    row = db.get(models.Task, created["entity_id"])

    assert row.done is False
    assert row.completed_at is None

    result = execution.execute(db, user, {"op": "update_task", "id": row.id, "done": True})
    db.refresh(row)

    assert result["verified"] is True
    assert row.done is True
    assert row.completed_at is not None
    assert (utcnow() - row.completed_at) < timedelta(minutes=5)


def test_a_repeated_completion_keeps_the_original_timestamp(db, history):
    row = db.get(models.Task, "c-today")
    original = row.completed_at

    result = execution.execute(db, history, {"op": "update_task", "id": "c-today", "done": True})
    db.refresh(row)

    assert result["verified"] is True
    assert row.completed_at == original


def test_reopening_clears_the_timestamp_and_completing_again_records_a_new_one(db, history):
    reopened = execution.execute(db, history, {"op": "update_task", "id": "c-today", "done": False})
    row = db.get(models.Task, "c-today")
    db.refresh(row)

    assert reopened["verified"] is True
    assert row.done is False
    assert row.completed_at is None

    again = execution.execute(db, history, {"op": "update_task", "id": "c-today", "done": True})
    db.refresh(row)

    assert again["verified"] is True
    assert row.completed_at is not None
    assert row.completed_at != datetime(2026, 11, 13, 4, 30), "a new completion gets a new stamp"
    assert row.completed_at > datetime(2026, 11, 13, 4, 30)


def test_a_task_created_already_complete_is_stamped(db):
    user = models.User(name="C", email="c@local.dev", password_hash="x")
    db.add(user)
    db.commit()

    created = execution.execute(db, user, {"op": "add_task", "text": "Already done", "done": True})
    row = db.get(models.Task, created["entity_id"])

    assert row.done is True
    assert row.completed_at is not None


def test_the_rest_path_uses_the_same_rule(db, history):
    row = models.Task(id="rest-1", user_id=history.id, text="REST task", done=False,
                      created_at=datetime(2026, 11, 1))
    db.add(row)
    db.commit()

    _apply_task(row, {"done": True})
    db.commit()
    assert row.completed_at is not None
    stamp = row.completed_at

    _apply_task(row, {"done": True})
    db.commit()
    assert row.completed_at == stamp, "repeating done must not re-date it"

    _apply_task(row, {"done": False})
    db.commit()
    assert row.done is False and row.completed_at is None


def test_a_legacy_completed_row_keeps_a_null_timestamp(db, history):
    row = db.get(models.Task, "c-legacy")
    original = row.completed_at

    execution.execute(db, history, {"op": "update_task", "id": "c-legacy", "done": True})
    db.refresh(row)

    assert original is None
    assert row.completed_at is None, "a repeat must not invent a completion date"


# ── history ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("period,expected", [
    ("today", ["Completed this morning"]),
    ("yesterday", ["Completed yesterday"]),
    ("week", ["Completed this morning", "Completed yesterday", "Completed Monday"]),
    ("month", ["Completed this morning", "Completed yesterday", "Completed Monday"]),
    ("last7", ["Completed this morning", "Completed yesterday", "Completed Monday"]),
    ("last30", ["Completed this morning", "Completed yesterday", "Completed Monday"]),
    ("recent", ["Completed this morning", "Completed yesterday", "Completed Monday",
                "Completed last month"]),
])
def test_completion_history_periods(db, history, period, expected):
    facts = task_intel.completed_tasks(db, history, period=period, today=TODAY)

    assert facts["status"] == "ok"
    assert names(facts) == expected
    assert facts["count"] == len(expected)


def test_history_is_ordered_newest_first(db, history):
    facts = task_intel.completed_tasks(db, history, period="recent", today=TODAY)

    stamps = [task["completed_at"] for task in facts["tasks"]]
    assert stamps == sorted(stamps, reverse=True)


def test_a_missing_timestamp_is_reported_and_never_listed(db, history):
    facts = task_intel.completed_tasks(db, history, period="recent", today=TODAY)

    assert "Completed before the column existed" not in names(facts)
    assert facts["without_timestamp"] == 1


def test_another_users_completions_are_excluded(db, history):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Task(id="their-1", user_id=other.id, text="Their completion", done=True,
                       priority="medium", category="Work",
                       completed_at=datetime(2026, 11, 13, 5, 0)))
    db.commit()

    facts = task_intel.completed_tasks(db, history, period="today", today=TODAY)

    assert names(facts) == ["Completed this morning"]


def test_the_history_limit_and_truncation(db, history):
    facts = task_intel.completed_tasks(db, history, period="recent", today=TODAY, limit=2)

    assert facts["count"] == 4
    assert facts["shown"] == 2
    assert facts["truncated"] is True


def test_an_empty_period_is_no_data(db, history):
    facts = task_intel.completed_tasks(db, history, period="today", today=date(2027, 5, 1))

    assert facts["status"] == "no_data"
    assert facts["tasks"] == []
    assert "message" in facts


def test_local_days_are_converted_to_utc_instants(db, history):
    ist = task_intel.completed_tasks(db, history, period="today", today=TODAY, timezone_name=IST)

    assert ist["start_utc"] == "2026-11-12T18:30:00Z"
    assert ist["end_utc"] == "2026-11-13T18:30:00Z"
    assert ist["timezone"] == IST


def test_a_late_utc_completion_belongs_to_the_next_ist_day(db, history):
    db.add(models.Task(id="c-late", user_id=history.id, text="Completed late UTC", done=True,
                       priority="medium", category="Personal",
                       completed_at=datetime(2026, 11, 13, 20, 0)))
    db.commit()

    utc = task_intel.completed_tasks(db, history, period="today", today=TODAY)
    ist = task_intel.completed_tasks(db, history, period="today", today=TODAY, timezone_name=IST)

    assert "Completed late UTC" in names(utc)
    assert "Completed late UTC" not in names(ist), "20:00Z is 01:30 the next day in IST"


# ── progress ───────────────────────────────────────────────────────────────

def test_progress_counts_completed_pending_and_overdue(db, history):
    facts = task_intel.task_progress(db, history, period="month", today=TODAY)

    assert facts["completed_count"] == 3
    assert facts["pending_count"] == 3
    assert facts["overdue_count"] == 1
    assert facts["total_count"] == 8
    assert facts["completed_all_time"] == 5
    assert facts["without_timestamp"] == 1


def test_progress_is_user_scoped(db, history):
    other = models.User(name="Other", email="o2@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    for index in range(4):
        db.add(models.Task(id=f"t-other-{index}", user_id=other.id, text="theirs", done=False,
                           priority="medium", category="Work",
                           created_at=datetime(2026, 11, 1)))
    db.commit()

    facts = task_intel.task_progress(db, history, period="month", today=TODAY)

    assert facts["pending_count"] == 3
    assert facts["total_count"] == 8


def test_progress_does_not_offer_a_completion_rate(db, history):
    facts = task_intel.task_progress(db, history, period="month", today=TODAY)

    keys = " ".join(facts.keys()).lower()
    assert "rate" not in keys and "percent" not in keys
    assert facts["scope"]["completed_count"].startswith("completed in")
    assert facts["scope"]["pending_count"] == "currently incomplete"
    assert facts["scope"]["total_count"].startswith("every task")


def test_progress_period_is_independent_of_the_open_counts(db, history):
    month = task_intel.task_progress(db, history, period="month", today=TODAY)
    week = task_intel.task_progress(db, history, period="week", today=TODAY)

    assert month["completed_count"] == 3
    assert week["completed_count"] == 3
    assert month["pending_count"] == week["pending_count"] == 3


# ── routing and integration ────────────────────────────────────────────────

@pytest.mark.parametrize("message,period", [
    ("What did I complete today?", "today"),
    ("What did I finish this week?", "week"),
    ("Show my recently completed tasks.", "recent"),
    ("How many tasks did I complete this month?", "month"),
])
def test_completion_questions_route_to_history(db, history, message, period):
    analysis = analyse(db, history, message)

    assert analysis["intent"] == "tasks_completed"
    assert analysis["facts"]["period"] == period
    assert analysis["facts"]["count"] > 0


@pytest.mark.parametrize("message", [
    "How am I doing with my tasks?",
    "How many tasks are still pending?",
    "Compare my completed and pending tasks.",
])
def test_progress_questions_route_to_progress(db, history, message):
    analysis = analyse(db, history, message)

    assert analysis["intent"] == "tasks_progress"
    assert analysis["facts"]["completed_count"] == 3
    assert analysis["facts"]["pending_count"] == 3


def test_history_does_not_route_to_due_or_attention(db, history):
    assert analyse(db, history, "What did I complete today?")["intent"] == "tasks_completed"
    assert analyse(db, history, "What do I need to complete today?")["intent"] == "tasks_due"
    assert analyse(db, history, "What needs my attention?")["intent"] == "tasks_attention"
    assert analyse(db, history, "Show me overdue tasks.")["intent"] == "tasks_due"


def test_a_carried_finance_category_does_not_filter_history(db, history):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, history, "What did I complete today?", context=prior, turn=2)

    assert analysis["intent"] == "tasks_completed"
    assert analysis["facts"]["count"] == 1
    assert analysis["context"] == prior


def test_history_questions_apply_no_writes(db, history, conversation, scripted):
    scripted({"reply": "You completed one task.", "actions": []})

    turn = graph.run_turn(db, history, conversation.id, "What did I complete today?", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "tasks_completed"
    assert turn["applied"] == [] and turn["failed"] == []


def test_the_prompt_carries_the_completion_facts(db, history, conversation, scripted):
    model = scripted({"reply": "One task, completed this morning.", "actions": []})

    graph.run_turn(db, history, conversation.id, "What did I complete today?", [],
                   turn=1, today=TODAY)

    prompt = model.last_system
    assert "tasks_completed" in prompt
    assert "Completed this morning" in prompt
    assert "without_timestamp" in prompt


def test_creation_completion_and_rescheduling_still_work(db, history, conversation, scripted):
    scripted({"reply": "Added.", "actions": [
        {"op": "add_task", "text": "Prepare deck", "due": "2026-11-20", "priority": "high"}]},
        {"reply": "Moved.", "actions": [{"op": "update_task", "due": "2026-11-14"}]})

    created = graph.run_turn(db, history, conversation.id, "Add a task to prepare the deck", [],
                             turn=1, today=TODAY)
    moved = graph.run_turn(db, history, conversation.id, "Move it to tomorrow", [],
                           turn=2, today=TODAY)

    assert created["applied"] and created["applied"][0]["verified"]
    assert moved["applied"] and moved["applied"][0]["verified"]
    row = db.query(models.Task).filter(models.Task.user_id == history.id,
                                       models.Task.text == "Prepare deck").one()
    assert row.due == date(2026, 11, 14)
    assert row.completed_at is None
