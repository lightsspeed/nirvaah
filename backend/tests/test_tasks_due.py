"""Task 29.1 — due and overdue task intelligence, answered from SQL.

Today is Friday 13 November 2026 in every test, so weekday and week-end rules
are pinned to a known day.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import execution, graph, planner
from app.agent import tasks as task_intel


TODAY = date(2026, 11, 13)          # Friday; ISO week runs 2026-11-09 .. 11-15

LEDGER = [
    ("Overdue rent paperwork", date(2026, 11, 5), "high", "Finance", False),
    ("Overdue library book", date(2026, 11, 12), "medium", "Personal", False),
    ("Due today tax proof", date(2026, 11, 13), "high", "Finance", False),
    ("Tomorrow submit report", date(2026, 11, 14), "medium", "Work", False),
    ("Sunday family lunch", date(2026, 11, 15), "low", "Personal", False),
    ("Next Friday review deck", date(2026, 11, 20), "high", "Work", False),
    ("Next month renew insurance", date(2026, 12, 20), "medium", "Finance", False),
    ("No date idea", None, "low", "Personal", False),
    ("Already done overdue", date(2026, 11, 1), "high", "Work", True),
]


@pytest.fixture()
def book(db):
    user = models.User(name="Book", email="book@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for index, (text, due, priority, category, done) in enumerate(LEDGER):
        db.add(models.Task(id=f"t{index}", user_id=user.id, text=text, due=due,
                           priority=priority, category=category, done=done))
    db.commit()
    return user


def texts(facts):
    return [row["text"] for row in facts["tasks"]]


def analyse(db, user, message, context=None, turn=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn)


# ── windows ────────────────────────────────────────────────────────────────

def test_overdue_tasks_oldest_first_with_days_overdue(db, book):
    facts = task_intel.due_tasks(db, book, window="overdue", today=TODAY)

    assert facts["status"] == "ok"
    assert facts["count"] == 2
    assert texts(facts) == ["Overdue rent paperwork", "Overdue library book"]
    assert [row["days_overdue"] for row in facts["tasks"]] == [8, 1]
    assert facts["end"] == "2026-11-12"
    assert facts["buckets"] == {"overdue": 2, "today": 0, "upcoming": 0}


def test_tasks_due_today(db, book):
    facts = task_intel.due_tasks(db, book, window="today", today=TODAY)

    assert texts(facts) == ["Due today tax proof"]
    assert facts["tasks"][0]["days_overdue"] is None
    assert facts["tasks"][0]["bucket"] == "today"


def test_tasks_due_tomorrow(db, book):
    facts = task_intel.due_tasks(db, book, window="tomorrow", today=TODAY)

    assert texts(facts) == ["Tomorrow submit report"]
    assert facts["tasks"][0]["days_until"] == 1


def test_upcoming_horizon(db, book):
    facts = task_intel.due_tasks(db, book, window="upcoming", days=3, today=TODAY)

    assert texts(facts) == ["Tomorrow submit report", "Sunday family lunch"]
    assert facts["start"] == "2026-11-14"
    assert facts["end"] == "2026-11-16"


def test_week_window_ends_on_sunday(db, book):
    facts = task_intel.due_tasks(db, book, window="week", today=TODAY)

    assert facts["end"] == "2026-11-15"
    assert texts(facts) == ["Due today tax proof", "Tomorrow submit report",
                           "Sunday family lunch"]
    assert facts["buckets"] == {"overdue": 0, "today": 1, "upcoming": 2}


def test_open_window_splits_the_buckets(db, book):
    facts = task_intel.due_tasks(db, book, window="open", days=7, today=TODAY)

    assert facts["buckets"] == {"overdue": 2, "today": 1, "upcoming": 3}
    assert facts["count"] == 6
    assert "Next month renew insurance" not in texts(facts)


def test_completed_tasks_are_never_returned(db, book):
    for window in ("overdue", "today", "tomorrow", "week", "open"):
        facts = task_intel.due_tasks(db, book, window=window, days=7, today=TODAY)
        assert "Already done overdue" not in texts(facts)


def test_another_users_tasks_are_excluded(db, book):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Task(id="other-1", user_id=other.id, text="Their overdue task",
                       due=date(2026, 11, 1), priority="high", category="Work", done=False))
    db.commit()

    facts = task_intel.due_tasks(db, book, window="overdue", today=TODAY)

    assert facts["count"] == 2
    assert "Their overdue task" not in texts(facts)


def test_an_empty_window_is_no_data(db, book):
    facts = task_intel.due_tasks(db, book, window="date", on=date(2026, 11, 16), today=TODAY)

    assert facts["status"] == "no_data"
    assert facts["count"] == 0
    assert facts["tasks"] == []
    assert facts["buckets"] == {"overdue": 0, "today": 0, "upcoming": 0}
    assert "message" in facts


def test_the_result_limit_is_honoured(db, book):
    facts = task_intel.due_tasks(db, book, window="overdue", today=TODAY, limit=1)

    assert facts["count"] == 2
    assert facts["shown"] == 1
    assert facts["truncated"] is True
    assert texts(facts) == ["Overdue rent paperwork"]


def test_undated_tasks_never_appear_in_dated_windows(db, book):
    for window in ("overdue", "today", "tomorrow", "week", "upcoming", "open"):
        facts = task_intel.due_tasks(db, book, window=window, days=7, today=TODAY)
        assert "No date idea" not in texts(facts)


# ── date resolution ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,window", [
    ("Show me overdue tasks.", "overdue"),
    ("What do I need to complete today?", "today"),
    ("What is due tomorrow?", "tomorrow"),
    ("What is coming up this week?", "week"),
    ("What's on my plate?", "open"),
    ("What is due in the next 3 days?", "upcoming"),
])
def test_relative_expressions_resolve(message, window):
    assert task_intel.window_for(message, TODAY)["window"] == window


def test_next_n_days_sets_the_horizon():
    resolved = task_intel.window_for("what is due in the next 4 days", TODAY)

    assert resolved["window"] == "upcoming"
    assert resolved["days"] == 4
    assert resolved["start"] == "2026-11-14"
    assert resolved["end"] == "2026-11-17"


def test_a_bare_weekday_is_the_next_occurrence_strictly_after_today():
    friday_asked_on_friday = task_intel.window_for("what is due on Friday?", TODAY)
    monday = task_intel.window_for("what is due on Monday?", TODAY)

    assert friday_asked_on_friday["date"] == "2026-11-20", "a Friday question on Friday is not today"
    assert monday["date"] == "2026-11-16"


def test_next_weekday_is_the_following_iso_week():
    resolved = task_intel.window_for("what is due next Monday?", TODAY)

    assert resolved["date"] == "2026-11-16", "Monday of the following ISO week"
    assert task_intel.window_for("what is due next Friday?", TODAY)["date"] == "2026-11-20"


def test_the_week_ends_on_sunday():
    assert task_intel.week_end(TODAY) == date(2026, 11, 15)
    assert task_intel.week_end(date(2026, 11, 9)) == date(2026, 11, 15), "a Monday's week ends that Sunday"


@pytest.mark.parametrize("message", [
    "What is due sometime soon?",
    "What is due in a few days?",
    "What is due on the 15th?",
])
def test_vague_expressions_ask_instead_of_guessing(message):
    resolved = task_intel.window_for(message, TODAY)

    assert resolved["ambiguous"] is True
    assert "Which day" in resolved["question"]


# ── planner routing ────────────────────────────────────────────────────────

@pytest.mark.parametrize("message,window", [
    ("What do I need to complete today?", "today"),
    ("Show me overdue tasks.", "overdue"),
    ("What is due tomorrow?", "tomorrow"),
    ("What is coming up this week?", "week"),
    ("What's on my plate?", "open"),
])
def test_task_questions_route_to_tasks_due(db, book, message, window):
    analysis = analyse(db, book, message)

    assert analysis["intent"] == "tasks_due"
    assert analysis["facts"]["window"] == window
    assert analysis["facts"]["status"] == "ok"


def test_a_vague_task_question_asks_for_a_day(db, book):
    analysis = analyse(db, book, "What is due sometime soon?")

    assert analysis["intent"] == "clarify"
    assert "Which day" in analysis["facts"]["question"]


def test_a_finance_category_never_narrows_a_task_question(db, book):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, book, "Show me overdue tasks.", context=prior, turn=2)

    assert analysis["intent"] == "tasks_due"
    assert analysis["facts"]["count"] == 2
    assert analysis["context"] == prior, "the finance thread is left exactly as it was"


def test_finance_questions_still_work_after_a_task_turn(db, book):
    assert analyse(db, book, "How much did I spend in November?")["intent"] == "month_summary"


def test_a_task_question_is_not_a_write(db, book, conversation, scripted):
    scripted({"reply": "Two tasks are overdue.", "actions": []})

    turn = graph.run_turn(db, book, conversation.id, "Show me overdue tasks.", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "tasks_due"
    assert turn["applied"] == []
    assert turn["failed"] == []


def test_the_prompt_carries_the_task_rows(db, book, conversation, scripted):
    model = scripted({"reply": "Two tasks are overdue.", "actions": []})

    turn = graph.run_turn(db, book, conversation.id, "Show me overdue tasks.", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "tasks_due"
    prompt = model.last_system
    assert "tasks_due" in prompt
    assert "Overdue rent paperwork" in prompt
    assert "days_overdue" in prompt


# ── neighbours ─────────────────────────────────────────────────────────────

def test_task_creation_still_works(db, book):
    result = execution.execute(db, book, {"op": "add_task", "text": "Book dentist",
                                          "due": "2026-11-20", "priority": "high"})

    assert result["success"] and result["verified"]
    assert db.query(models.Task).filter(models.Task.user_id == book.id,
                                        models.Task.text == "Book dentist").count() == 1


def test_task_completion_still_works(db, book):
    result = execution.execute(db, book, {"op": "update_task", "id": "t2", "done": True})

    assert result["success"] and result["verified"]
    assert db.get(models.Task, "t2").done is True
    assert task_intel.due_tasks(db, book, window="today", today=TODAY)["count"] == 0


def test_focus_rescheduling_still_works(db, book, conversation, scripted):
    scripted({"reply": "Added.", "actions": [
        {"op": "add_task", "text": "Prepare deck", "due": "2026-11-16", "priority": "high"}]},
        {"reply": "Moved to Friday.", "actions": [
            {"op": "update_task", "due": "2026-11-20"}]})

    graph.run_turn(db, book, conversation.id, "Add a task to prepare the deck", [],
                   turn=1, today=TODAY)
    moved = graph.run_turn(db, book, conversation.id, "Move it to Friday", [], turn=2, today=TODAY)

    assert moved["applied"] and moved["applied"][0]["verified"] is True
    row = db.query(models.Task).filter(models.Task.user_id == book.id,
                                       models.Task.text == "Prepare deck").one()
    assert row.due == date(2026, 11, 20)
