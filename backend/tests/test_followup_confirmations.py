"""Task 30.5 — follow-ups and confirmations.

Four live conversations failed in the same place. The model had the right record
in every one of them; `guard_action` refused the write because the *user's*
sentence did not repeat that record's name:

    "Actually, make it Wednesday."
    "yes, do it"
    "Change its due date to the 25th, but keep everything else unchanged."
    "Now change the journal entry to say I completed the VPC module."

The tests below replay those four conversations exactly, then pin the rules that
keep confirmations honest: a bare "yes" approves only what this conversation was
just working with, nothing else.
"""

from __future__ import annotations

from datetime import date

from app import models
from app.agent import api as agent_api
from app.agent.confirm import is_confirmation


TODAY = date(2026, 11, 14)          # a Saturday
FRIDAY = "2026-11-20"
MONDAY = "2026-11-16"
WEDNESDAY = "2026-11-18"
SUNDAY = "2026-11-15"
THE_25TH = "2026-11-25"


def say(db, user, conversation, scripted, message, reply, actions=None, *, calls=None):
    """One API turn, the way the app drives it."""
    payload = {"reply": reply, "actions": actions or []}
    if calls is None:
        scripted(payload)
    return agent_api.send_message(conversation.id, agent_api.MessageIn(message=message),
                                  db=db, user=user, today=TODAY, timezone_name="Asia/Kolkata")


def tasks(db, user):
    return db.query(models.Task).filter(models.Task.user_id == user.id).all()


def journals(db, user):
    return db.query(models.JournalEntry).filter(models.JournalEntry.user_id == user.id).all()


def find_task(db, user, text):
    return (db.query(models.Task)
            .filter(models.Task.user_id == user.id, models.Task.text == text).one())


# ── Case 1: consecutive updates on the same task ───────────────────────────

def test_case1_actually_make_it_wednesday(db, user, conversation, scripted):
    created = say(db, user, conversation, scripted,
                  "Create a task to submit my project report on Friday.",
                  "Added a task to submit your project report by Friday, 20 November 2026.",
                  [{"op": "add_task", "text": "Submit project report", "due": FRIDAY}])
    assert len(created["applied"]) == 1, created
    task = find_task(db, user, "Submit project report")
    before = len(tasks(db, user))

    moved = say(db, user, conversation, scripted, "Move the task to Monday.",
                "Moved the task to Monday, 16 November 2026.",
                [{"op": "update_task", "text": "Submit project report", "due": MONDAY}])
    assert [r["operation"] for r in moved["applied"]] == ["update_task"], moved

    again = say(db, user, conversation, scripted, "Actually, make it Wednesday.",
                'Moving "Submit project report" to Wednesday, 18 November 2026.',
                [{"op": "update_task", "text": "Submit project report", "due": WEDNESDAY}])

    assert [r["operation"] for r in again["applied"]] == ["update_task"], again
    assert again["applied"][0]["entity_id"] == task.id
    db.refresh(task)
    assert task.due == date(2026, 11, 18)
    assert len(tasks(db, user)) == before, "no duplicate task"


# ── Case 2: confirming a proposed transaction change ───────────────────────

def test_case2_yes_do_it_after_a_proposal(db, user, conversation, scripted):
    created = say(db, user, conversation, scripted,
                  "I spent ₹950 on a movie yesterday. Record it under Entertainment.",
                  "Recorded ₹950 under Entertainment for yesterday's movie.",
                  [{"op": "add_transaction", "kind": "expense", "amount": 950,
                    "category": "Entertainment", "description": "Movie",
                    "txn_date": "2026-11-13"}])
    assert len(created["applied"]) == 1, created
    txn = db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id, models.Transaction.amount == 950).one()

    # The assistant proposes the change instead of making it.
    proposal = say(db, user, conversation, scripted, "Change its category to Shopping.",
                   "I can change the ₹950 movie transaction from 13 November 2026 to the "
                   "Shopping category.", [])
    assert proposal["applied"] == [] and proposal["failed"] == []

    confirmed = say(db, user, conversation, scripted, "Yes, do it.",
                    "Changed the ₹950 movie transaction to Shopping.",
                    [{"op": "update_transaction", "description": "Movie",
                      "category": "Shopping"}])

    assert [r["operation"] for r in confirmed["applied"]] == ["update_transaction"], confirmed
    assert confirmed["applied"][0]["verified"] is True
    db.refresh(txn)
    assert txn.category == "Shopping"
    assert float(txn.amount) == 950.0
    assert db.query(models.Transaction).filter(
        models.Transaction.user_id == user.id, models.Transaction.amount == 950).count() == 1


# ── Case 3: a field correction that restates "keep everything else" ────────

def test_case3_change_its_due_date_to_the_25th(db, user, conversation, scripted):
    say(db, user, conversation, scripted, "Create a task to pay my broadband bill on the 20th.",
        "Added a task to pay your broadband bill on 20 November 2026.",
        [{"op": "add_task", "text": "Pay broadband bill", "due": FRIDAY,
          "priority": "high", "category": "Bills"}])
    task = find_task(db, user, "Pay broadband bill")

    fixed = say(db, user, conversation, scripted,
                "Change its due date to the 25th, but keep everything else unchanged.",
                "Moved the broadband bill task to 25 November 2026.",
                [{"op": "update_task", "text": "Pay broadband bill", "due": THE_25TH}])

    assert [r["operation"] for r in fixed["applied"]] == ["update_task"], fixed
    db.refresh(task)
    assert task.due == date(2026, 11, 25)
    assert task.text == "Pay broadband bill"
    assert task.priority == "high", "unrequested fields must not change"
    assert task.category == "Bills"


# ── Case 4: journal content correction while a task is also in play ────────

def test_case4_change_the_journal_entry_only(db, user, conversation, scripted):
    say(db, user, conversation, scripted,
        "Create a task to complete my Terraform module and add a journal entry about "
        "today's learning progress.",
        "Adding a task to complete your Terraform module and a journal entry.",
        [{"op": "add_task", "text": "Complete Terraform module", "due": FRIDAY},
         {"op": "add_journal", "title": "Learning progress",
          "description": "Studied the Terraform module today", "date": "2026-11-14"}])
    task = find_task(db, user, "Complete Terraform module")
    entry = (db.query(models.JournalEntry)
             .filter(models.JournalEntry.user_id == user.id,
                     models.JournalEntry.title == "Learning progress").one())

    say(db, user, conversation, scripted, "Move the task to Sunday.",
        "Moving the Terraform module task to Sunday, 15 November 2026.",
        [{"op": "update_task", "text": "Complete Terraform module", "due": SUNDAY}])
    db.refresh(task)
    assert task.due == date(2026, 11, 15)

    task_due_before = task.due
    corrected = say(db, user, conversation, scripted,
                    "Now change the journal entry to say I completed the VPC module.",
                    "Updated the journal entry to say you completed the VPC module.",
                    [{"op": "update_journal", "title": "Learning progress",
                      "description": "Completed the VPC module"}])

    assert [r["operation"] for r in corrected["applied"]] == ["update_journal"], corrected
    db.refresh(entry)
    db.refresh(task)
    assert entry.description == "Completed the VPC module"
    assert entry.title == "Learning progress", "only the content changes"
    assert task.due == task_due_before, "the task must not move"
    assert task.text == "Complete Terraform module"


# ── confirmation rules ─────────────────────────────────────────────────────

def test_is_confirmation_recognises_the_short_forms():
    for message in ("Yes", "yes, do it", "Go ahead", "Proceed", "That's correct",
                    "ok", "Please do it", "Yes please", "Confirmed"):
        assert is_confirmation(message), message


def test_is_confirmation_rejects_new_content():
    for message in ("yes, but change the amount to 1200", "go ahead and add a task",
                    "Move the task to Monday.", "", "no"):
        assert not is_confirmation(message), message


def test_a_confirmation_with_nothing_pending_writes_nothing(db, user, conversation, scripted):
    before = len(tasks(db, user))
    result = say(db, user, conversation, scripted, "Yes, do it.",
                 "Done.", [{"op": "update_task", "due": MONDAY}])

    assert result["applied"] == []
    assert result["failed"], "a confirmation with no proposal is refused, not executed"
    assert "nothing waiting for confirmation" in (result["content"] or "").lower()
    assert len(tasks(db, user)) == before


def test_a_confirmation_for_a_different_record_is_refused(db, user, conversation, scripted):
    """The conversation is about one task; the model reaches for an older one."""
    say(db, user, conversation, scripted, "Create a task to submit my report on Friday.",
        "Added it.", [{"op": "add_task", "text": "Submit report", "due": FRIDAY}])
    fresh = find_task(db, user, "Submit report")
    stale = db.get(models.Task, "seed-wheel-balancing")
    stale_due = stale.due

    result = say(db, user, conversation, scripted, "Yes, do it.",
                 "Done.", [{"op": "update_task", "id": "seed-wheel-balancing", "due": MONDAY}])

    assert result["applied"] == []
    assert "does not match what I proposed" in (result["content"] or "")
    db.refresh(stale)
    db.refresh(fresh)
    assert stale.due == stale_due, "the unrelated task must not move"
    assert fresh.due == date(2026, 11, 20)


def test_a_confirmation_for_the_current_record_is_allowed(db, user, conversation, scripted):
    say(db, user, conversation, scripted, "Create a task to call the plumber on Friday.",
        "Added it.", [{"op": "add_task", "text": "Call the plumber", "due": FRIDAY}])
    task = find_task(db, user, "Call the plumber")

    result = say(db, user, conversation, scripted, "Go ahead.",
                 "Moved it.",
                 [{"op": "update_task", "text": "Call the plumber", "due": MONDAY}])

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    assert task.due == date(2026, 11, 16)


# ── ambiguity and type boundaries ─────────────────────────────────────────

def test_two_tasks_from_one_turn_stay_distinguishable(db, user, conversation, scripted):
    say(db, user, conversation, scripted,
        "Create a task to submit my report on Friday and a task to book the meeting room.",
        "Added both tasks.",
        [{"op": "add_task", "text": "Submit report", "due": FRIDAY},
         {"op": "add_task", "text": "Book the meeting room", "due": FRIDAY}])
    report = find_task(db, user, "Submit report")
    room = find_task(db, user, "Book the meeting room")

    ambiguous = say(db, user, conversation, scripted, "Move the task to Monday.",
                    "Which task?", [{"op": "update_task", "due": MONDAY}])
    assert ambiguous["applied"] == []
    assert "which task" in (ambiguous["content"] or "").lower()
    for task in (report, room):
        db.refresh(task)
        assert task.due == date(2026, 11, 20)

    named = say(db, user, conversation, scripted,
                "Move the 'Book the meeting room' task to Monday.",
                "Moved it.", [{"op": "update_task", "text": "Book the meeting room",
                               "due": MONDAY}])
    assert [r["operation"] for r in named["applied"]] == ["update_task"], named
    db.refresh(report)
    db.refresh(room)
    assert room.due == date(2026, 11, 16)
    assert report.due == date(2026, 11, 20), "the other task must not move"


def test_a_task_update_never_touches_a_similar_journal(db, user, conversation, scripted):
    db.add(models.JournalEntry(id="seed-similar-journal", user_id=user.id,
                               title="Submit report notes", description="Original",
                               event_date=TODAY))
    db.commit()
    say(db, user, conversation, scripted, "Create a task to submit report on Friday.",
        "Added it.", [{"op": "add_task", "text": "Submit report", "due": FRIDAY}])
    task = find_task(db, user, "Submit report")

    result = say(db, user, conversation, scripted, "Actually, make it Wednesday.",
                 'Moving it to Wednesday.', [{"op": "update_task", "text": "Submit report",
                                              "due": WEDNESDAY}])

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    entry = db.get(models.JournalEntry, "seed-similar-journal")
    db.refresh(entry)
    assert task.due == date(2026, 11, 18)
    assert entry.description == "Original" and entry.event_date == TODAY


def test_a_journal_update_never_touches_a_task(db, user, conversation, scripted):
    db.add(models.JournalEntry(id="seed-journal-x", user_id=user.id, title="Learning log",
                               description="Started", event_date=TODAY))
    db.commit()
    task = db.get(models.Task, "seed-wheel-balancing")
    task_due, task_text = task.due, task.text

    result = say(db, user, conversation, scripted,
                 "Change the Learning log journal entry to say the module is done.",
                 "Updated it.", [{"op": "update_journal", "title": "Learning log",
                                  "description": "Module is done"}])

    assert [r["operation"] for r in result["applied"]] == ["update_journal"], result
    entry = db.get(models.JournalEntry, "seed-journal-x")
    db.refresh(entry)
    db.refresh(task)
    assert entry.description == "Module is done"
    assert task.due == task_due and task.text == task_text


def test_the_update_is_verified_before_it_is_reported(db, user, conversation, scripted):
    say(db, user, conversation, scripted, "Create a task to water the plants on Friday.",
        "Added it.", [{"op": "add_task", "text": "Water the plants", "due": FRIDAY}])

    result = say(db, user, conversation, scripted, "Actually, make it Wednesday.",
                 "Moved it.", [{"op": "update_task", "text": "Water the plants",
                                "due": WEDNESDAY}])

    applied = result["applied"][0]
    assert applied["verified"] is True
    assert applied["changes"]["due"] == {"before": FRIDAY, "after": WEDNESDAY}
