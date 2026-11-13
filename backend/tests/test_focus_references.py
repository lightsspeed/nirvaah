"""Task 27.5.2 — conversational reference resolution in chat_focus.

The prompt already promised "the last one", "the previous one", "the most recent
one"; focus now recognises them. These tests run the real execution flow and
pin the safety rules: one unambiguous referent only, the conversation's own
record only, the authenticated user only, and deletes still need approval.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import execution, focus, graph


TODAY = date(2026, 11, 13)


def turn(db, user, conversation, scripted, message, payload, *, number=1, chat_context=None):
    model = scripted(payload)
    result = graph.run_turn(db, user, conversation.id, message, [], turn=number,
                            today=TODAY, chat_context=chat_context)
    return result, model


def create_task(db, user, conversation, scripted, text="Pay rent", *, number=1):
    result, _ = turn(db, user, conversation, scripted, f"create a task to {text}",
                     {"reply": "Added.", "actions": [
                         {"op": "add_task", "text": text, "due": "2026-11-20"}]},
                     number=number)
    assert result["applied"], result
    return result["applied"][0]["entity_id"]


def test_delete_the_last_one_after_creating_a_task(db, user, conversation, scripted):
    task_id = create_task(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, "And delete the last one.",
                     {"reply": "Deleting that task.", "actions": [{"op": "delete_task"}]},
                     number=2)

    assert [p["operation"] for p in result["pending"]] == ["delete_task"]
    assert result["pending"][0]["entity_id"] == task_id
    assert db.get(models.Task, task_id) is not None, "a delete must wait for approval"

    confirmed = execution.execute(db, user, {"op": "delete_task", "id": task_id},
                                  context={"today": TODAY, "tz": "UTC"})
    assert confirmed["success"], confirmed
    assert db.get(models.Task, task_id) is None


def test_two_tasks_then_the_last_one_deletes_the_newest(db, user, conversation, scripted):
    result, _ = turn(db, user, conversation, scripted, "add two tasks: pay rent and call the bank",
                     {"reply": "Added both.", "actions": [
                         {"op": "add_task", "text": "Pay rent"},
                         {"op": "add_task", "text": "Call the bank"}]},
                     number=1)
    first, second = [a["entity_id"] for a in result["applied"]]

    result, _ = turn(db, user, conversation, scripted, "Delete the last one.",
                     {"reply": "Deleting that task.", "actions": [{"op": "delete_task"}]},
                     number=2)

    assert result["pending"][0]["entity_id"] == second
    assert db.get(models.Task, first) is not None
    assert db.get(models.Task, second) is not None, "nothing is deleted before approval"


def test_mark_the_most_recent_one_completed(db, user, conversation, scripted):
    task_id = create_task(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, "Mark the most recent one as completed.",
                     {"reply": "Marked done.", "actions": [{"op": "update_task", "done": True}]},
                     number=2)

    assert result["applied"], result
    assert db.get(models.Task, task_id).done is True


def test_change_its_due_date_to_friday(db, user, conversation, scripted):
    task_id = create_task(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, "Change its due date to Friday.",
                     {"reply": "Moved it.", "actions": [{"op": "update_task", "due": "2026-11-20"}]},
                     number=2)

    assert result["applied"], result
    assert db.get(models.Task, task_id).due == date(2026, 11, 20)


def test_cancel_the_previous_reminder(db, user, conversation, scripted):
    # Nirvaah has no reminder entity: a reminder is a task with a due date, and
    # the model maps "cancel the previous reminder" to delete_task.
    task_id = create_task(db, user, conversation, scripted, "Pay rent")

    result, _ = turn(db, user, conversation, scripted, "Cancel the previous reminder.",
                     {"reply": "Removing it.", "actions": [{"op": "delete_task"}]},
                     number=2)

    assert [p["operation"] for p in result["pending"]] == ["delete_task"]
    assert result["pending"][0]["entity_id"] == task_id
    assert db.get(models.Task, task_id) is not None


def test_a_different_record_type_asks_instead_of_guessing(db, user, conversation, scripted):
    result, _ = turn(db, user, conversation, scripted, "note down the wifi password is on the fridge",
                     {"reply": "Noted.", "actions": [{"op": "add_note", "title": "Wifi password"}]},
                     number=1)
    assert result["applied"], result
    note_id = result["applied"][0]["entity_id"]

    result, _ = turn(db, user, conversation, scripted, "Delete the last one.",
                     {"reply": "Deleting.", "actions": [{"op": "delete_task"}]},
                     number=2)

    assert not result["pending"] and not result["applied"]
    assert "Which task do you mean?" in result["reply"]
    assert db.get(models.Note, note_id) is not None


def test_without_a_conversation_record_it_asks(db, user, conversation, scripted):
    before = db.query(models.Task).filter(models.Task.user_id == user.id).count()

    result, _ = turn(db, user, conversation, scripted, "Delete the last one.",
                     {"reply": "Deleting.", "actions": [{"op": "delete_task"}]})

    assert not result["pending"] and not result["applied"]
    assert "Which task do you mean?" in result["reply"]
    assert db.query(models.Task).filter(models.Task.user_id == user.id).count() == before


def test_another_users_record_is_never_resolved(db, user, conversation, scripted):
    from app.agent import resolve as resolver
    from app.security import hash_password

    other = models.User(email="other@local.dev", password_hash=hash_password("x"),
                        name="Other", currency="INR")
    db.add(other)
    db.commit()
    theirs = models.Task(id="their-task", user_id=other.id, text="Pay their rent")
    db.add(theirs)
    db.commit()

    resolution = resolver.resolve(db, user, "task", raw_id="their-task")
    assert resolution.status == "invalid_id"

    result = execution.execute(db, user, {"op": "delete_task", "id": "their-task"},
                              context={"today": TODAY, "tz": "UTC"})
    assert not result["success"]
    assert db.get(models.Task, "their-task") is not None

    # And an empty focus in this conversation must not reach across users either.
    result, _ = turn(db, user, conversation, scripted, "Delete the last one.",
                     {"reply": "Deleting.", "actions": [{"op": "delete_task"}]})
    assert not result["pending"]
    assert db.get(models.Task, "their-task") is not None


@pytest.mark.parametrize("message", ["Delete it.", "Cancel it.", "Update that."])
def test_existing_pronoun_writes_still_resolve(db, user, conversation, scripted, message):
    task_id = create_task(db, user, conversation, scripted)

    result, _ = turn(db, user, conversation, scripted, message,
                     {"reply": "Deleting.", "actions": [{"op": "delete_task"}]},
                     number=2)

    assert result["pending"][0]["entity_id"] == task_id


def test_analytics_context_does_not_hijack_reference_resolution(db, user, conversation, scripted):
    context = {"intent": "list_transactions", "category": "Groceries", "month": "2026-05",
               "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}
    task_id = create_task(db, user, conversation, scripted, "Pay rent")

    result, model = turn(db, user, conversation, scripted, "And delete the last one.",
                         {"reply": "Deleting that task.", "actions": [{"op": "delete_task"}]},
                         number=3, chat_context=context)

    assert result["pending"][0]["entity_id"] == task_id
    assert "VERIFIED ANALYTICS (intent:" not in model.last_system


@pytest.mark.parametrize("message,expected", [
    ("And delete the last one.", True),
    ("Delete the latest task.", True),
    ("Update the previous one.", True),
    ("Mark the most recent one as completed.", True),
    ("Cancel the previous reminder.", True),
    ("The previous month was expensive.", False),
    ("Create a task to pay rent.", False),
])
def test_reference_phrases(message, expected):
    assert focus.looks_like_followup(message) is expected
