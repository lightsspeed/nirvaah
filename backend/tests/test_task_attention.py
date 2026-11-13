"""Task 29.2 — personal task awareness: deterministic attention ranking.

Today is Friday 13 November 2026. Fillar tasks are created with explicit
`created_at` values so age (`days_open`) is pinned rather than dependent on the
wall clock.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app import models
from app.agent import execution, graph, planner
from app.agent import tasks as task_intel


TODAY = date(2026, 11, 13)

LEDGER = [
    # text, due, priority, created, done
    ("File GST return", date(2026, 11, 8), "high", date(2026, 11, 1), False),
    ("Return library book", date(2026, 11, 11), "medium", date(2026, 10, 20), False),
    ("Submit tax proof", date(2026, 11, 13), "high", date(2026, 11, 5), False),
    ("Send status update", date(2026, 11, 14), "medium", date(2026, 11, 10), False),
    ("Draft annual plan", date(2026, 12, 15), "high", date(2026, 11, 12), False),
    ("Read that article", None, "low", date(2026, 10, 1), False),
    ("Buy milk", None, "low", date(2026, 11, 13), False),
    ("Already finished", date(2026, 11, 1), "high", date(2026, 10, 1), True),
]


@pytest.fixture()
def board(db):
    user = models.User(name="Board", email="board@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for index, (text, due, priority, created, done) in enumerate(LEDGER):
        db.add(models.Task(id=f"a{index}", user_id=user.id, text=text, due=due,
                           priority=priority, category="Personal", done=done,
                           created_at=datetime.combine(created, datetime.min.time())))
    db.commit()
    return user


def rows(facts):
    return [(t["attention_rank"], t["text"]) for t in facts["tasks"]]


def analyse(db, user, message, context=None, turn=None):
    return planner.analyse(db, user, message, today=TODAY, context=context, turn=turn)


# ── ranking ────────────────────────────────────────────────────────────────

def test_attention_ranking_follows_the_documented_order(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)

    assert facts["status"] == "ok"
    assert rows(facts) == [
        (1, "File GST return"),        # overdue + high priority
        (2, "Return library book"),    # other overdue
        (3, "Submit tax proof"),       # high priority, due today
        (4, "Send status update"),     # due tomorrow
        (5, "Draft annual plan"),      # high priority, far due date
        (6, "Read that article"),      # open a long time
    ]


def test_a_task_with_no_reason_is_not_listed(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)

    assert "Buy milk" not in [t["text"] for t in facts["tasks"]]
    assert facts["count"] == 6


def test_overdue_high_priority_outranks_plain_overdue(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)
    by_text = {t["text"]: t for t in facts["tasks"]}

    assert by_text["File GST return"]["attention_rank"] == 1
    assert by_text["Return library book"]["attention_rank"] == 2
    assert by_text["File GST return"]["days_overdue"] == 5
    assert by_text["Return library book"]["days_overdue"] == 2


def test_due_today_and_tomorrow_are_separated(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)
    by_text = {t["text"]: t for t in facts["tasks"]}

    assert by_text["Submit tax proof"]["days_until"] == 0
    assert by_text["Submit tax proof"]["attention_reasons"] == ["due today", "high priority"]
    assert by_text["Send status update"]["days_until"] == 1
    assert by_text["Send status update"]["attention_reasons"] == ["due tomorrow"]


def test_a_far_due_high_priority_task_is_listed_for_priority_only(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)
    task = [t for t in facts["tasks"] if t["text"] == "Draft annual plan"][0]

    assert task["attention_rank"] == 5
    assert task["attention_reasons"] == ["high priority"]
    assert task["days_until"] == 32


def test_age_is_reported_as_days_open_not_as_neglect(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)
    task = [t for t in facts["tasks"] if t["text"] == "Read that article"][0]

    assert task["attention_rank"] == 6
    assert task["days_open"] == 43
    assert task["attention_reasons"] == ["open for 43 days"]
    assert "neglect" not in " ".join(task["attention_reasons"]).lower()


def test_one_task_can_carry_several_reasons_without_being_repeated(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)
    task = [t for t in facts["tasks"] if t["text"] == "Return library book"][0]

    assert task["attention_reasons"] == ["overdue by 2 days", "open for 24 days"]
    assert [t["id"] for t in facts["tasks"]] == list(dict.fromkeys(t["id"] for t in facts["tasks"]))


def test_priority_breaks_ties_within_one_rank(db):
    user = models.User(name="Tie", email="tie@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    for task_id, text, priority, created in (("x1", "Low overdue", "low", date(2026, 11, 1)),
                                             ("x2", "Medium overdue", "medium", date(2026, 11, 2)),
                                             ("x3", "High overdue", "high", date(2026, 11, 3))):
        db.add(models.Task(id=task_id, user_id=user.id, text=text, due=date(2026, 11, 9),
                           priority=priority, category="Personal", done=False,
                           created_at=datetime.combine(created, datetime.min.time())))
    db.commit()

    facts = task_intel.attention_tasks(db, user, today=TODAY)

    assert [t["text"] for t in facts["tasks"]] == ["High overdue", "Medium overdue", "Low overdue"]


def test_completed_tasks_are_excluded(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)

    assert "Already finished" not in [t["text"] for t in facts["tasks"]]


def test_another_users_tasks_are_excluded(db, board):
    other = models.User(name="Other", email="other@local.dev", password_hash="x")
    db.add(other)
    db.commit()
    db.add(models.Task(id="other-1", user_id=other.id, text="Their overdue high task",
                       due=date(2026, 11, 1), priority="high", category="Work", done=False,
                       created_at=datetime(2026, 10, 1)))
    db.commit()

    facts = task_intel.attention_tasks(db, board, today=TODAY)

    assert facts["count"] == 6
    assert "Their overdue high task" not in [t["text"] for t in facts["tasks"]]


def test_the_limit_is_honoured_and_reported(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY, limit=2)

    assert facts["count"] == 6
    assert facts["shown"] == 2
    assert facts["truncated"] is True
    assert rows(facts) == [(1, "File GST return"), (2, "Return library book")]


def test_nothing_to_do_is_no_data(db):
    user = models.User(name="Calm", email="calm@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.add(models.Task(id="calm-1", user_id=user.id, text="Buy milk", priority="low",
                       category="Personal", done=False,
                       created_at=datetime(2026, 11, 13)))
    db.commit()

    facts = task_intel.attention_tasks(db, user, today=TODAY)

    assert facts["status"] == "no_data"
    assert facts["count"] == 0
    assert facts["tasks"] == []
    assert "need attention" in facts["message"].lower()


def test_the_rules_and_priority_order_are_in_the_facts(db, board):
    facts = task_intel.attention_tasks(db, board, today=TODAY)

    assert facts["priority_order"] == ["high", "medium", "low"]
    assert facts["stale_days"] == 14
    assert len(facts["rules"]) == 6
    assert task_intel.priority_weight("high") < task_intel.priority_weight("medium")
    assert task_intel.priority_weight("unknown") == 3


# ── routing ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "What needs my attention?",
    "Which tasks should I focus on?",
    "What important tasks am I neglecting?",
    "What should I work on first?",
    "Show me tasks I should not delay.",
])
def test_attention_requests_reach_the_attention_list(db, board, message):
    analysis = analyse(db, board, message)

    assert analysis["intent"] == "tasks_attention"
    assert analysis["facts"]["count"] == 6
    assert analysis["facts"]["tasks"][0]["text"] == "File GST return"


def test_attention_is_not_a_task_lookup(db, board):
    assert analyse(db, board, "What do I need to complete today?")["intent"] == "tasks_due"
    assert analyse(db, board, "Show me overdue tasks.")["intent"] == "tasks_due"
    assert analyse(db, board, "What's on my plate?")["intent"] == "tasks_due"


def test_a_carried_finance_category_does_not_narrow_attention(db, board):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-11",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = analyse(db, board, "What needs my attention?", context=prior, turn=2)

    assert analysis["intent"] == "tasks_attention"
    assert analysis["facts"]["count"] == 6
    assert analysis["context"] == prior


def test_an_attention_question_is_not_a_write(db, board, conversation, scripted):
    scripted({"reply": "Start with the GST return.", "actions": []})

    turn = graph.run_turn(db, board, conversation.id, "What needs my attention?", [],
                          turn=1, today=TODAY)

    assert turn["analytics"]["intent"] == "tasks_attention"
    assert turn["applied"] == []
    assert turn["failed"] == []


def test_the_prompt_carries_the_ranked_rows(db, board, conversation, scripted):
    model = scripted({"reply": "Start with the GST return.", "actions": []})

    graph.run_turn(db, board, conversation.id, "What should I work on first?", [],
                   turn=1, today=TODAY)

    prompt = model.last_system
    assert "tasks_attention" in prompt
    assert "File GST return" in prompt
    assert "attention_reasons" in prompt
    assert "overdue by 5 days" in prompt


# ── neighbours keep working ────────────────────────────────────────────────

def test_tasks_due_still_answers_date_questions(db, board):
    analysis = analyse(db, board, "Show me overdue tasks.")

    assert analysis["intent"] == "tasks_due"
    assert analysis["facts"]["window"] == "overdue"
    assert analysis["facts"]["count"] == 2


def test_task_creation_and_completion_still_work(db, board):
    created = execution.execute(db, board, {"op": "add_task", "text": "Call the bank",
                                            "due": "2026-11-20", "priority": "high"})
    assert created["success"] and created["verified"]

    done = execution.execute(db, board, {"op": "update_task", "id": "a2", "done": True})
    assert done["success"] and done["verified"]

    facts = task_intel.attention_tasks(db, board, today=TODAY)
    assert "Submit tax proof" not in [t["text"] for t in facts["tasks"]]
    assert "Call the bank" in [t["text"] for t in facts["tasks"]]


def test_rescheduling_still_works_through_focus(db, board, conversation, scripted):
    scripted({"reply": "Added.", "actions": [
        {"op": "add_task", "text": "Prepare deck", "due": "2026-11-20", "priority": "high"}]},
        {"reply": "Moved.", "actions": [{"op": "update_task", "due": "2026-11-14"}]})

    graph.run_turn(db, board, conversation.id, "Add a task to prepare the deck", [],
                   turn=1, today=TODAY)
    moved = graph.run_turn(db, board, conversation.id, "Move it to tomorrow", [],
                           turn=2, today=TODAY)

    assert moved["applied"] and moved["applied"][0]["verified"]
    row = db.query(models.Task).filter(models.Task.user_id == board.id,
                                       models.Task.text == "Prepare deck").one()
    assert row.due == date(2026, 11, 14)
