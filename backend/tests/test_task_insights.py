"""Task 30.1 — deterministic, evidence-backed task insights.

Today is Friday 13 November 2026. The "board" user has enough open work to
trigger all four rules; the "calm" user sits below every threshold.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app import models
from app.agent import execution, graph, planner
from app.agent import tasks as task_intel


TODAY = date(2026, 11, 13)
STALE = datetime(2026, 10, 1)


@pytest.fixture()
def board(db):
    """Two high-priority overdue, two medium overdue, three due in 48h, three stale."""
    user = models.User(name="Board", email="board-insights@local.dev", password_hash="x")
    db.add(user)
    db.commit()

    def add(task_id, text, *, due=None, priority="medium", done=False, created=STALE,
            completed=None):
        db.add(models.Task(id=task_id, user_id=user.id, text=text, done=done, due=due,
                           priority=priority, category="Personal", created_at=created,
                           completed_at=completed))

    add("h1", "File GST return", due=TODAY - timedelta(days=8), priority="high")
    add("h2", "Submit audit form", due=TODAY - timedelta(days=3), priority="high")
    add("m1", "Return library book", due=TODAY - timedelta(days=1))
    add("m2", "Pay the cleaner", due=TODAY - timedelta(days=2), created=datetime(2026, 11, 5))
    add("t1", "Submit tax proof", due=TODAY, priority="high", created=datetime(2026, 11, 5))
    add("tm1", "Send status update", due=TODAY + timedelta(days=1), created=datetime(2026, 11, 5))
    add("tm2", "Book cab", due=TODAY + timedelta(days=1), created=datetime(2026, 11, 5))
    add("done-old", "Finished overdue thing", done=True, due=TODAY - timedelta(days=5),
        priority="high", completed=datetime(2026, 11, 12, 6, 0))
    db.commit()
    return user


@pytest.fixture()
def calm(db):
    """Two overdue, two due soon, two long-open: nothing reaches a threshold."""
    user = models.User(name="Calm", email="calm-insights@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for index, (due, created) in enumerate((
            (TODAY - timedelta(days=2), datetime(2026, 11, 10)),
            (TODAY - timedelta(days=1), datetime(2026, 11, 10)),
            (TODAY, datetime(2026, 11, 10)),
            (TODAY + timedelta(days=1), datetime(2026, 11, 10)))):
        db.add(models.Task(id=f"c{index}", user_id=user.id, text=f"Small task {index}",
                           due=due, priority="medium", category="Personal",
                           created_at=created))
    db.commit()
    return user


def insights(db, user, **kwargs):
    return task_intel.generate_task_insights(db, user, today=TODAY, **kwargs)


def by_type(facts):
    grouped: dict[str, list[dict]] = {}
    for item in facts["insights"]:
        grouped.setdefault(item["type"], []).append(item)
    return grouped


# ── Rule A ─────────────────────────────────────────────────────────────────

def test_rule_a_reports_each_high_priority_overdue_task(db, board):
    facts = insights(db, board)
    critical = by_type(facts)["high_priority_overdue"]

    assert [item["severity"] for item in critical] == ["critical", "critical"]
    assert [item["dedupe_key"] for item in critical] == ["task_overdue_high:h1",
                                                        "task_overdue_high:h2"]
    first = critical[0]
    assert '"File GST return" is overdue by 8 days' in first["message"]
    assert first["evidence"] == {"task_id": "h1", "text": "File GST return",
                                 "due": "2026-11-05", "days_overdue": 8, "priority": "high",
                                 "high_priority_overdue_total": 2}
    assert first["task_ids"] == ["h1"]
    assert first["recommended_action"]


def test_rule_a_ignores_medium_overdue_and_completed_tasks(db, calm):
    facts = insights(db, calm)

    assert facts["counts"]["critical"] == 0
    assert "high_priority_overdue" not in by_type(facts)


def test_a_completed_high_priority_overdue_task_raises_nothing(db, board):
    facts = insights(db, board)

    assert "task_overdue_high:done-old" not in [item["dedupe_key"] for item in facts["insights"]]


# ── Rule B ─────────────────────────────────────────────────────────────────

def test_rule_b_fires_at_three_overdue_tasks(db, board):
    facts = insights(db, board)
    cluster = by_type(facts)["overdue_cluster"][0]

    assert cluster["severity"] == "warning"
    assert cluster["dedupe_key"] == "overdue_cluster"
    assert cluster["evidence"]["overdue_count"] == 4
    assert cluster["evidence"]["high_priority_overdue"] == 2
    assert cluster["evidence"]["oldest_days_overdue"] == 8
    assert "4 open tasks are past due" in cluster["message"]


def test_rule_b_stays_quiet_below_three_overdue(db, calm):
    assert "overdue_cluster" not in by_type(insights(db, calm))


def test_rule_a_and_rule_b_say_different_things(db, board):
    facts = insights(db, board)
    grouped = by_type(facts)
    cluster_message = grouped["overdue_cluster"][0]["message"]
    messages = [item["message"] for item in facts["insights"]]

    assert len(messages) == len(set(messages)), "no two insights share a message"
    assert "File GST return" not in cluster_message, "the cluster names counts, not tasks"
    for item in grouped["high_priority_overdue"]:
        assert item["message"] != cluster_message


# ── Rule C ─────────────────────────────────────────────────────────────────

def test_rule_c_fires_at_three_deadlines_inside_48_hours(db, board):
    facts = insights(db, board)
    soon = by_type(facts)["due_soon"][0]

    assert soon["severity"] == "warning"
    assert soon["dedupe_key"] == "due_soon_48h"
    assert soon["evidence"]["due_today"] == 1
    assert soon["evidence"]["due_tomorrow"] == 2
    assert soon["evidence"]["total"] == 3
    assert "3 tasks are due within the next 48 hours" in soon["message"]
    assert soon["evidence"]["task_ids"] == ["t1", "tm1", "tm2"]


def test_rule_c_stays_quiet_below_three_deadlines(db, calm):
    assert "due_soon" not in by_type(insights(db, calm))


# ── Rule D ─────────────────────────────────────────────────────────────────

def test_rule_d_fires_at_three_long_open_tasks(db, board):
    facts = insights(db, board)
    stale = by_type(facts)["long_open"][0]

    assert stale["severity"] == "info"
    assert stale["dedupe_key"] == "long_open_14d"
    assert stale["evidence"]["long_open_count"] == 3
    assert stale["evidence"]["threshold_days"] == 14
    assert stale["evidence"]["oldest_days_open"] == 43
    assert "at least 14 days" in stale["message"]
    assert set(stale["evidence"]["task_ids"]) == {"h1", "h2", "m1"}


def test_rule_d_stays_quiet_below_three_long_open_tasks(db, calm):
    assert "long_open" not in by_type(insights(db, calm))


def test_time_alone_is_reported_as_days_open_not_neglect(db, board):
    stale = by_type(insights(db, board))["long_open"][0]

    assert "neglect" not in stale["message"].lower()


# ── shape, dedupe and safety ───────────────────────────────────────────────

def test_every_insight_carries_the_contract(db, board):
    facts = insights(db, board)

    for item in facts["insights"]:
        assert set(item) == {"id", "dedupe_key", "type", "severity", "title", "message",
                             "evidence", "task_ids", "recommended_action", "evaluated_at"}
        assert item["id"] == item["dedupe_key"]
        assert item["severity"] in ("info", "warning", "critical")
        assert item["evidence"] and item["task_ids"]
        assert item["evaluated_at"].endswith("Z")


def test_severity_orders_the_list(db, board):
    facts = insights(db, board)

    order = [item["severity"] for item in facts["insights"]]
    assert order == ["critical", "critical", "warning", "warning", "info"]
    assert [item["type"] for item in facts["insights"]] == [
        "high_priority_overdue", "high_priority_overdue", "overdue_cluster", "due_soon",
        "long_open"]


def test_dedupe_keys_are_stable_and_unique(db, board):
    first = [item["dedupe_key"] for item in insights(db, board)["insights"]]
    second = [item["dedupe_key"] for item in insights(db, board)["insights"]]

    assert first == second
    assert len(first) == len(set(first))


def test_the_limit_truncates_the_list_but_not_the_counts(db, board):
    facts = insights(db, board, limit=2)

    assert facts["count"] == 5
    assert facts["shown"] == 2
    assert facts["truncated"] is True
    assert facts["counts"] == {"critical": 2, "warning": 2, "info": 1}
    assert len(facts["insights"]) == 2


def test_no_qualifying_insights_is_an_explicit_empty_result(db, calm):
    facts = insights(db, calm)

    assert facts["status"] == "no_data"
    assert facts["count"] == 0
    assert facts["insights"] == []
    assert facts["counts"] == {"critical": 0, "warning": 0, "info": 0}
    assert "No significant task-related insights" in facts["message"]


def test_another_users_tasks_never_appear(db, board, calm):
    calm_keys = [item["dedupe_key"] for item in insights(db, calm)["insights"]]
    board_ids = {task_id for item in insights(db, board)["insights"] for task_id in item["task_ids"]}

    assert "task_overdue_high:h1" not in calm_keys
    assert "h1" not in {task_id for item in insights(db, calm)["insights"]
                        for task_id in item["task_ids"]}
    assert board_ids and "c0" not in board_ids


def test_insight_generation_writes_nothing(db, board):
    before = db.query(models.Task).filter(models.Task.user_id == board.id).count()
    done_before = db.query(models.Task).filter(models.Task.user_id == board.id,
                                               models.Task.done.is_(True)).count()

    insights(db, board)

    assert db.query(models.Task).filter(models.Task.user_id == board.id).count() == before
    assert db.query(models.Task).filter(models.Task.user_id == board.id,
                                        models.Task.done.is_(True)).count() == done_before


# ── routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Is there anything I should know?",
    "Do you have any insights for me?",
    "What's happening with my tasks?",
    "Anything important I might be missing?",
    "Give me my personal insights.",
])
def test_insight_requests_route_to_insights(db, board, message):
    analysis = planner.analyse(db, board, message, today=TODAY)

    assert analysis["intent"] == "personal_insights"
    assert analysis["facts"]["count"] == 5


@pytest.mark.parametrize("message,intent", [
    ("What do I need to complete today?", "tasks_due"),
    ("Show me overdue tasks.", "tasks_due"),
    ("What needs my attention?", "tasks_attention"),
    ("Which tasks should I focus on?", "tasks_attention"),
    ("Give me my weekly review.", "tasks_weekly_review"),
    ("How was my week?", "tasks_weekly_review"),
    ("What did I complete today?", "tasks_completed"),
    ("How am I doing with my tasks?", "tasks_progress"),
    ("How much did I spend in May?", "month_summary"),
    ("Which category did I spend the most on?", "category_ranking"),
])
def test_explicit_requests_keep_their_intents(db, board, message, intent):
    assert planner.analyse(db, board, message, today=TODAY)["intent"] == intent


def test_an_insight_request_applies_no_actions(db, board, conversation, scripted):
    scripted({"reply": "Two high-priority tasks are overdue.", "actions": []})

    turn = graph.run_turn(db, board, conversation.id, "Is there anything I should know?", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "personal_insights"
    assert turn["applied"] == [] and turn["failed"] == []
    assert db.get(models.Task, "h1").done is False


def test_a_carried_finance_category_does_not_affect_insights(db, board):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = planner.analyse(db, board, "Do you have any insights for me?", today=TODAY,
                               context=prior, turn=2)

    assert analysis["intent"] == "personal_insights"
    assert analysis["facts"]["count"] == 5
    assert analysis["context"] == prior


def test_the_prompt_carries_the_insights(db, board, conversation, scripted):
    model = scripted({"reply": "Two high-priority tasks are overdue.", "actions": []})

    graph.run_turn(db, board, conversation.id, "Give me my personal insights.", [],
                   turn=1, today=TODAY)

    prompt = model.last_system
    assert "personal_insights" in prompt
    assert "File GST return" in prompt
    assert "recommended_action" in prompt
    assert "due_soon" in prompt


def test_resolving_an_insight_removes_it_from_the_next_evaluation(db, board):
    before = insights(db, board)
    assert "task_overdue_high:h1" in [item["dedupe_key"] for item in before["insights"]]

    execution.execute(db, board, {"op": "update_task", "id": "h1", "done": True})
    after = insights(db, board)

    assert "task_overdue_high:h1" not in [item["dedupe_key"] for item in after["insights"]]
