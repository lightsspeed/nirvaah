"""Task 30.3 — contextual follow-ups that update a task.

The conversation under test is the one that failed in the app:

    turn 1  "Create a task to submit my project report on Friday and add a journal
             entry that I completed the first draft today."
    turn 2  "Move the task to Monday."

Turn 1 writes two records, so the conversation's single focus row ends up on the
journal entry. Turn 2 then says "the task" — no name of its own — and the update
was resolved against the whole instruction sentence instead of the task that was
just created.

These tests pin the behaviour the app promises: the reference resolves from the
conversation, only the requested field changes, nothing is created twice, and an
ambiguous reference asks instead of guessing.
"""

from __future__ import annotations

from datetime import date

from app import models
from app.agent import resolve


TODAY = date(2026, 11, 13)          # a Friday
FRIDAY = date(2026, 11, 20)         # "Friday" in the request
MONDAY = date(2026, 11, 23)         # "Monday" after it

CREATE_BOTH = "Create a task to submit my project report on Friday and add a journal entry that I completed the first draft today."

TASK_ACTION = {"op": "add_task", "text": "Submit project report", "due": FRIDAY.isoformat(),
               "priority": "medium", "category": "Work"}
JOURNAL_ACTION = {"op": "add_journal", "title": "Completed first draft of project report",
                  "description": "Finished the first draft", "date": TODAY.isoformat()}


def turn(db, user, conversation, scripted, message, payload, *, number=1, recent=None):
    from app.agent import graph
    model = scripted(payload)
    result = graph.run_turn(db, user, conversation.id, message, [], turn=number,
                            today=TODAY, recent_records=recent)
    return result, model


def create_both(db, user, conversation, scripted):
    result, _ = turn(db, user, conversation, scripted, CREATE_BOTH,
                     {"reply": "Added the task and the journal entry.",
                      "actions": [TASK_ACTION, JOURNAL_ACTION]})
    assert len(result["applied"]) == 2, result
    task = db.query(models.Task).filter(models.Task.user_id == user.id,
                                        models.Task.text == "Submit project report").one()
    entry = db.query(models.JournalEntry).filter(
        models.JournalEntry.user_id == user.id,
        models.JournalEntry.title == "Completed first draft of project report").one()
    return task, entry


def recent_from(result):
    """What the API would remember from the previous turn."""
    found: dict[str, list[str]] = {}
    for item in result.get("applied") or []:
        kind = item.get("entity_type") or ""
        if str(item.get("operation") or "").startswith("add_"):
            found.setdefault(kind, []).append(str(item.get("entity_id")))
    return found


def task_count(db, user):
    return db.query(models.Task).filter(models.Task.user_id == user.id).count()


# ── 1. the reported failure ────────────────────────────────────────────────

def test_move_the_task_to_monday(db, user, conversation, scripted):
    """Turn 2 names no record: the task created a moment ago is the target."""
    task, entry = create_both(db, user, conversation, scripted)
    entry_date, entry_title = entry.event_date, entry.title
    before = task_count(db, user)

    result, _ = turn(db, user, conversation, scripted, "Move the task to Monday.",
                     {"reply": "Moved it to Monday.", "actions": [
                         {"op": "update_task", "due": MONDAY.isoformat()}]},
                     number=2, recent={"task": [task.id]})

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    assert not result["failed"]

    db.refresh(task)
    db.refresh(entry)
    assert task.due == MONDAY
    assert task.text == "Submit project report", "only the requested field changes"
    assert task_count(db, user) == before, "an update must never create a task"

    assert entry.event_date == entry_date and entry.title == entry_title, \
        "the journal entry must not be touched"


def test_move_the_task_when_the_model_copies_the_instruction(db, user, conversation, scripted):
    """A model that writes the sentence into `text` must not defeat the lookup."""
    task, _ = create_both(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, "Move the task to Monday.",
                     {"reply": "Moved it to Monday.", "actions": [
                         {"op": "update_task", "text": "Move the task to Monday.",
                          "due": MONDAY.isoformat()}]},
                     number=2, recent={"task": [task.id]})

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    assert task.due == MONDAY
    assert task.text == "Submit project report", "the instruction is not a new title"


def test_change_its_due_date_to_monday(db, user, conversation, scripted):
    task, _ = create_both(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, "Change its due date to Monday.",
                     {"reply": "Changed the due date.", "actions": [
                         {"op": "update_task", "due": MONDAY.isoformat()}]},
                     number=2, recent={"task": [task.id]})

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    assert task.due == MONDAY


def test_explicit_name_with_the_whole_instruction_attached(db, user, conversation, scripted):
    """The user names the task and restates the change in one sentence."""
    task, _ = create_both(db, user, conversation, scripted)
    message = ("Move the due date of the task 'Submit project report' from Friday to "
               "Monday. Keep the task title and all other details unchanged.")

    result, _ = turn(db, user, conversation, scripted, message,
                     {"reply": "Moved the due date.", "actions": [
                         {"op": "update_task",
                          "text": "Submit project report from Friday to Monday",
                          "due": MONDAY.isoformat()}]},
                     number=2)

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    assert task.due == MONDAY
    assert task.text == "Submit project report"
    assert task.category == "Work"


# ── 2. an ambiguous reference asks ─────────────────────────────────────────

def test_two_recent_tasks_ask_which_one(db, user, conversation, scripted):
    """Two tasks created in the same turn: no silent pick."""
    result, _ = turn(db, user, conversation, scripted,
                     "Create a task to submit my project report on Friday and a task to book the meeting room.",
                     {"reply": "Added both tasks.", "actions": [
                         {"op": "add_task", "text": "Submit project report", "due": FRIDAY.isoformat()},
                         {"op": "add_task", "text": "Book the meeting room", "due": FRIDAY.isoformat()}]})
    assert len(result["applied"]) == 2, result
    ids = [r["entity_id"] for r in result["applied"] if r["entity_type"] == "task"]

    before = task_count(db, user)
    second, _ = turn(db, user, conversation, scripted, "Move the task to Monday.",
                     {"reply": "Moved it to Monday.", "actions": [
                         {"op": "update_task", "due": MONDAY.isoformat()}]},
                     number=2, recent={"task": ids})

    assert second["applied"] == [], second
    assert second["failed"], "an ambiguous reference must be reported, not guessed"
    assert "which" in (second["reply"] or "").lower()
    for task_id in ids:
        db.refresh(db.get(models.Task, task_id))
        assert db.get(models.Task, task_id).due == FRIDAY, "neither task may move"
    assert task_count(db, user) == before


# ── 3. the resolver itself ─────────────────────────────────────────────────

def test_instruction_words_are_not_record_names(db, user):
    """The sentence around the name must not dilute the match."""
    db.add(models.Task(id="seed-report", user_id=user.id, text="Submit project report",
                       due=FRIDAY, priority="medium", category="Work"))
    db.commit()

    found = resolve.resolve(db, user, "task",
                            query="Move the due date of the task Submit project report from "
                                  "Friday to Monday. Keep the task title and all other details busy")
    assert found.ok, found.message
    assert found.row.text == "Submit project report"


def test_weekdays_alone_do_not_identify_a_record(db, user):
    """'Move it to Monday' must not match a task because of the weekday."""
    db.add(models.Task(id="seed-monday", user_id=user.id, text="Monday standup notes",
                       due=FRIDAY, priority="low", category="Work"))
    db.commit()

    found = resolve.resolve(db, user, "task", query="Move the task to Monday")
    assert not found.ok, f"matched {getattr(found.row, 'text', '')!r} on the weekday alone"


# ── 4. the API carries the previous turn's records ─────────────────────────

def test_the_api_hands_the_previous_turns_records_to_the_turn(db, user, conversation, scripted):
    """The real path: two requests, no test-only plumbing."""
    from app.agent import api as agent_api

    scripted(
        {"reply": "Added the task and the journal entry.",
         "actions": [TASK_ACTION, JOURNAL_ACTION]},
        {"reply": "Moved it to Monday.",
         "actions": [{"op": "update_task", "due": MONDAY.isoformat()}]},
    )
    before = task_count(db, user)

    first = agent_api.send_message(conversation.id, agent_api.MessageIn(message=CREATE_BOTH),
                                   db=db, user=user, today=TODAY, timezone_name="Asia/Kolkata")
    assert len(first["applied"]) == 2, first
    before = task_count(db, user)

    task = db.query(models.Task).filter(models.Task.user_id == user.id,
                                        models.Task.text == "Submit project report").one()

    second = agent_api.send_message(conversation.id,
                                    agent_api.MessageIn(message="Move the task to Monday."),
                                    db=db, user=user, today=TODAY, timezone_name="Asia/Kolkata")

    assert [r["operation"] for r in second["applied"]] == ["update_task"], second
    db.refresh(task)
    assert task.due == MONDAY
    assert task_count(db, user) == before


def test_recent_records_keeps_the_newest_creation_per_kind():
    """Only creations count, and the newest creating turn wins."""
    import json

    from app.agent.api import _recent_records

    class Msg:
        def __init__(self, role, applied):
            self.role = role
            self.meta = json.dumps({"applied": applied})

    old = Msg("assistant", [{"operation": "add_task", "entity_type": "task", "entity_id": "old-task"}])
    newest = Msg("assistant", [
        {"operation": "add_task", "entity_type": "task", "entity_id": "new-task"},
        {"operation": "add_journal", "entity_type": "journal", "entity_id": "new-journal"},
    ])
    update_only = Msg("assistant", [
        {"operation": "update_task", "entity_type": "task", "entity_id": "untouched"}])
    user_turn = Msg("user", [])

    found = _recent_records([old, update_only, newest, user_turn])
    assert found["task"] == ["new-task"]
    assert found["journal"] == ["new-journal"]


def test_recent_records_tolerates_a_broken_meta():
    from app.agent.api import _recent_records

    class Msg:
        role = "assistant"
        meta = "not json"

    assert _recent_records([Msg()]) == {}
