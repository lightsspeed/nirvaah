"""Task 29.4 — the weekly review, composed from the task intelligence that exists.

Today is Friday 13 November 2026, so the local week is Mon 9 – Sun 15.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import models
from app.agent import execution, graph, planner
from app.agent import tasks as task_intel


TODAY = date(2026, 11, 13)
IST = "Asia/Kolkata"


@pytest.fixture()
def week(db):
    """Completions this week, older completions, open work in every section."""
    user = models.User(name="Week", email="week@local.dev", password_hash="x")
    db.add(user)
    db.commit()

    def add(task_id, text, *, done=False, due=None, priority="medium", completed=None):
        db.add(models.Task(id=task_id, user_id=user.id, text=text, done=done, due=due,
                           priority=priority, category="Personal", completed_at=completed,
                           created_at=datetime(2026, 10, 1)))

    add("w1", "Completed Monday", done=True, completed=datetime(2026, 11, 9, 6, 0))
    add("w2", "Completed Wednesday", done=True, completed=datetime(2026, 11, 11, 9, 0))
    add("w3", "Completed today", done=True, completed=datetime(2026, 11, 13, 4, 30))
    add("w0", "Completed last week", done=True, completed=datetime(2026, 11, 5, 6, 0))
    add("legacy", "Legacy completion", done=True, completed=None)
    add("d1", "Finished but was due yesterday", done=True, due=TODAY - timedelta(days=1),
        completed=datetime(2026, 11, 12, 5, 0))
    add("o1", "File GST return", due=TODAY - timedelta(days=8), priority="high")
    add("o2", "Return library book", due=TODAY - timedelta(days=1))
    add("t1", "Submit tax proof", due=TODAY, priority="high")
    add("u1", "Send status update", due=TODAY + timedelta(days=1))
    add("u2", "Review deck", due=TODAY + timedelta(days=3))
    add("l1", "Plan the offsite", due=TODAY + timedelta(days=10))
    add("l2", "Pick a hobby", due=None, priority="low")
    db.commit()
    return user


def texts(section):
    return [task["text"] for task in section["tasks"]]


def review(db, user, **kwargs):
    return task_intel.weekly_review(db, user, today=TODAY, **kwargs)


# ── sections ───────────────────────────────────────────────────────────────

def test_this_weeks_completions(db, week):
    facts = review(db, week)

    completed = facts["sections"]["completed"]
    assert facts["completed_count"] == 4
    assert completed["count"] == 4
    assert texts(completed) == ["Completed today", "Finished but was due yesterday",
                                "Completed Wednesday", "Completed Monday"]


def test_the_week_is_monday_to_sunday(db, week):
    facts = review(db, week)

    assert facts["week_start"] == "2026-11-09"
    assert facts["week_end"] == "2026-11-15"


def test_week_boundaries_are_local_days(db, week):
    db.add(models.Task(id="late-sun", user_id=week.id, text="Sunday night, next in IST", done=True,
                       priority="medium", category="Personal",
                       completed_at=datetime(2026, 11, 15, 20, 0)))
    db.add(models.Task(id="sun", user_id=week.id, text="Sunday afternoon", done=True,
                       priority="medium", category="Personal",
                       completed_at=datetime(2026, 11, 15, 10, 0)))
    db.commit()

    facts = review(db, week, timezone_name=IST)

    assert "Sunday afternoon" in texts(facts["sections"]["completed"])
    assert "Sunday night, next in IST" not in texts(facts["sections"]["completed"]), \
        "20:00Z Sunday is 01:30 Monday in IST"
    assert facts["timezone"] == IST


def test_older_completions_and_untimestamped_rows_stay_out(db, week):
    completed = review(db, week)["sections"]["completed"]

    assert "Completed last week" not in texts(completed)
    assert "Legacy completion" not in texts(completed)
    assert review(db, week)["without_timestamp"] == 1


def test_pending_is_all_time_not_this_weeks_leftover(db, week):
    facts = review(db, week)

    assert facts["pending_count"] == 7, "every open task, whatever its due date"
    assert facts["pending_count"] != facts["completed_count"]
    assert facts["sections"]["pending"]["count"] == 2, "only the tasks no other section shows"
    assert texts(facts["sections"]["pending"]) == ["Plan the offsite", "Pick a hobby"]


def test_overdue_tasks_and_days_overdue(db, week):
    facts = review(db, week)

    assert facts["overdue_count"] == 2
    overdue = facts["sections"]["overdue"]
    assert texts(overdue) == ["File GST return", "Return library book"]
    assert [task["days_overdue"] for task in overdue["tasks"]] == [8, 1]


def test_upcoming_covers_the_next_seven_days(db, week):
    facts = review(db, week)

    upcoming = facts["sections"]["upcoming"]
    assert facts["upcoming_count"] == 2
    assert upcoming["start"] == "2026-11-14"
    assert upcoming["end"] == "2026-11-20"
    assert texts(upcoming) == ["Send status update", "Review deck"]


def test_attention_reuses_the_ranking_and_its_reasons(db, week):
    facts = review(db, week)
    attention = facts["sections"]["attention"]

    assert facts["attention_count"] == 7
    assert attention["tasks"][0]["text"] == "File GST return"
    assert attention["tasks"][0]["attention_rank"] == 1
    assert "overdue by 8 days" in attention["tasks"][0]["attention_reasons"]
    assert "high priority" in attention["tasks"][0]["attention_reasons"]


def test_overlapping_tasks_are_labelled_across_sections(db, week):
    facts = review(db, week)
    attention = {task["text"]: task for task in facts["sections"]["attention"]["tasks"]}

    assert attention["File GST return"]["also_listed_in"] == ["overdue"]
    assert attention["Send status update"]["also_listed_in"] == ["upcoming"]
    assert attention["Plan the offsite"]["also_listed_in"] == ["pending"]
    assert "also_listed_in" not in attention["Submit tax proof"]


def test_completed_tasks_never_appear_as_open(db, week):
    facts = review(db, week)

    for name in ("pending", "overdue", "attention", "upcoming"):
        assert "Finished but was due yesterday" not in texts(facts["sections"][name])


def test_another_users_tasks_are_excluded(db, week):
    other = models.User(name="Other", email="other-week@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Task(id="their-overdue", user_id=other.id, text="Their overdue",
                       due=TODAY - timedelta(days=2), priority="high", category="Work"))
    db.add(models.Task(id="their-done", user_id=other.id, text="Their completion", done=True,
                       priority="medium", category="Work",
                       completed_at=datetime(2026, 11, 12, 7, 0)))
    db.commit()

    facts = review(db, week)

    assert facts["completed_count"] == 4
    assert facts["pending_count"] == 7
    assert facts["overdue_count"] == 2


def test_counts_stay_full_when_the_lists_are_truncated(db, week):
    facts = review(db, week, limit=1)

    assert facts["completed_count"] == 4
    assert facts["pending_count"] == 7
    assert facts["overdue_count"] == 2
    assert facts["attention_count"] == 7
    assert facts["upcoming_count"] == 2
    for name in ("completed", "pending", "overdue", "attention", "upcoming"):
        section = facts["sections"][name]
        assert section["shown"] == 1
        assert section["truncated"] is True
        assert section["count"] > 1


def test_an_empty_week_is_reported_not_simulated(db):
    user = models.User(name="Empty", email="empty-week@local.dev", password_hash="x")
    db.add(user)
    db.commit()

    facts = review(db, user)

    assert facts["status"] == "no_data"
    assert facts["completed_count"] == 0
    assert facts["pending_count"] == 0
    assert facts["overdue_count"] == 0
    assert facts["upcoming_count"] == 0
    assert all(section["tasks"] == [] for section in facts["sections"].values())
    assert "message" in facts


def test_a_week_with_only_completions(db):
    user = models.User(name="Done", email="done-week@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.add(models.Task(id="only-done", user_id=user.id, text="Finished everything", done=True,
                       priority="medium", category="Personal",
                       completed_at=datetime(2026, 11, 12, 6, 0)))
    db.commit()

    facts = review(db, user)

    assert facts["status"] == "ok"
    assert facts["completed_count"] == 1
    assert facts["pending_count"] == 0
    assert facts["overdue_count"] == 0
    assert facts["upcoming_count"] == 0


def test_no_rate_or_score_is_offered(db, week):
    facts = review(db, week)

    flat = " ".join([str(key) for key in facts] + [str(key) for key in facts["scope"]]).lower()
    assert "rate" not in flat and "percent" not in flat and "score" not in flat
    assert facts["scope"]["completed_count"].startswith("completed this week")
    assert facts["scope"]["pending_count"] == "every task still open, any due date"


def test_completing_a_task_shows_up_in_the_next_review(db, week):
    execution.execute(db, week, {"op": "update_task", "id": "u2", "done": True})

    facts = review(db, week, timezone_name=IST)

    assert facts["pending_count"] == 6
    assert facts["sections"]["completed"]["count"] == 5
    assert "Review deck" in texts(facts["sections"]["completed"])
    assert "Review deck" not in texts(facts["sections"]["upcoming"])


# ── routing and integration ────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Give me my weekly review.",
    "How was my week?",
    "Summarize my task progress this week.",
    "What did I finish and what is still pending?",
    "What should I focus on next week?",
])
def test_weekly_review_requests_route_to_the_review(db, week, message):
    analysis = planner.analyse(db, week, message, today=TODAY)

    assert analysis["intent"] == "tasks_weekly_review"
    assert analysis["facts"]["week_start"] == "2026-11-09"
    assert analysis["facts"]["completed_count"] == 4


@pytest.mark.parametrize("message,intent", [
    ("What did I finish this week?", "tasks_completed"),
    ("How many tasks did I complete this month?", "tasks_completed"),
    ("How am I doing with my tasks?", "tasks_progress"),
    ("How many tasks are still pending?", "tasks_progress"),
    ("What do I need to complete today?", "tasks_due"),
    ("Show me overdue tasks.", "tasks_due"),
    ("What needs my attention?", "tasks_attention"),
])
def test_individual_task_questions_keep_their_intents(db, week, message, intent):
    assert planner.analyse(db, week, message, today=TODAY)["intent"] == intent


def test_a_review_applies_no_writes(db, week, conversation, scripted):
    scripted({"reply": "Four finished, seven open.", "actions": []})

    turn = graph.run_turn(db, week, conversation.id, "Give me my weekly review.", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "tasks_weekly_review"
    assert turn["applied"] == [] and turn["failed"] == []
    assert db.query(models.Task).filter(models.Task.user_id == week.id,
                                        models.Task.id == "o1").one().done is False


def test_a_carried_finance_category_does_not_filter_the_review(db, week):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = planner.analyse(db, week, "Give me my weekly review.", today=TODAY,
                               context=prior, turn=2)

    assert analysis["intent"] == "tasks_weekly_review"
    assert analysis["facts"]["completed_count"] == 4
    assert analysis["facts"]["pending_count"] == 7
    assert analysis["context"] == prior


def test_the_prompt_carries_the_review_facts(db, week, conversation, scripted):
    model = scripted({"reply": "Four finished, two overdue.", "actions": []})

    graph.run_turn(db, week, conversation.id, "How was my week?", [], turn=1, today=TODAY)

    prompt = model.last_system
    assert "tasks_weekly_review" in prompt
    assert "Completed Monday" in prompt
    assert "attention_reasons" in prompt
    assert "2026-11-09" in prompt


def test_finance_questions_are_unaffected(db, week):
    analysis = planner.analyse(db, week, "How much did I spend in May?", today=TODAY)

    assert analysis["intent"] == "month_summary"
