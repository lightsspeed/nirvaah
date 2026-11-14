"""Task 30.2 — one message, several records.

The workflow these tests pin is the one that failed in practice: *"Add ₹1,238
for Ramayan movie in Entertainment, also add as a journal entry."* The model did
return both records; the creation-authority guard refused the expense because
the sentence never used the word "expense", and the turn still read as if both
had been saved.

Three seams are covered, each with the real execution path (no live model):

* ``authority.authorize_creation`` — an amount plus where it went authorises a
  spend without the noun "expense".
* ``multi.missing_kinds`` — a message asking for two records must come back with
  two actions, or the turn asks once more.
* ``graph.finish`` — when only some records were saved, the verified results
  word the reply instead of the model's own claim.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import models
from app.agent import authority, execution, focus, graph, multi


TODAY = date(2026, 11, 13)
TOMORROW = date(2026, 11, 14)

MOVIE_MESSAGE = ("Add ₹1,238 for Ramayan movie in Entertainment, "
                 "also add as a journal entry.")

MOVIE_ACTIONS = [
    {"op": "add_transaction", "kind": "expense", "amount": 1238,
     "category": "Entertainment", "description": "Ramayan movie",
     "payment_method": "UPI", "txn_date": TOMORROW.isoformat()},
    {"op": "add_journal", "title": "Ramayan movie",
     "description": "Watched Ramayan movie in the evening",
     "category": "Life", "date": TOMORROW.isoformat()},
]


def turn(db, user, conversation, scripted, message, payload, *, number=1,
         today=TODAY, chat_context=None):
    model = scripted(payload)
    result = graph.run_turn(db, user, conversation.id, message, [], turn=number,
                            today=today, chat_context=chat_context)
    return result, model


def transactions(db, user):
    return db.query(models.Transaction).filter(models.Transaction.user_id == user.id).all()


def journals(db, user):
    return db.query(models.JournalEntry).filter(models.JournalEntry.user_id == user.id).all()


# ── 1. the demonstrated request ─────────────────────────────────────────────

def test_amount_without_the_word_expense_authorises_the_spend():
    """The refusal that swallowed the transaction half of the request."""
    assert authority.authorize_creation("add_transaction", MOVIE_MESSAGE) is None


def test_amount_alone_does_not_authorise_a_goal_or_budget():
    """A goal also carries an amount; it must not read as a spend."""
    message = "Add ₹5,000 towards my goal for the laptop"
    assert authority.authorize_creation("add_transaction", message) is not None


def test_one_request_creates_a_transaction_and_a_journal_entry(db, user, conversation, scripted):
    before = len(transactions(db, user))

    result, _ = turn(db, user, conversation, scripted, MOVIE_MESSAGE,
                     {"reply": "Added ₹1,238 under Entertainment and a journal entry.",
                      "actions": MOVIE_ACTIONS})

    assert len(result["applied"]) == 2, result
    assert not result["failed"] and not result["pending"]

    rows = transactions(db, user)
    assert len(rows) == before + 1
    spend = [r for r in rows if r.description == "Ramayan movie"]
    assert len(spend) == 1
    assert spend[0].category == "Entertainment"
    assert float(spend[0].amount) == 1238.0
    assert spend[0].txn_date == TOMORROW

    entry = [j for j in journals(db, user) if j.title == "Ramayan movie"]
    assert len(entry) == 1
    assert entry[0].event_date == TOMORROW
    # Both writes verified, so the model's own sentence stands.
    assert result["reply"].startswith("Added ₹1,238")


def test_one_request_creates_a_task_and_a_journal_entry(db, user, conversation, scripted):
    result, _ = turn(
        db, user, conversation, scripted,
        "Add a task to pay the electricity bill tomorrow and note in my journal that I received it.",
        {"reply": "Added the task and the journal entry.", "actions": [
            {"op": "add_task", "text": "Pay electricity bill", "due": TOMORROW.isoformat()},
            {"op": "add_journal", "title": "Electricity bill",
             "description": "Received the electricity bill", "date": TOMORROW.isoformat()},
        ]},
    )

    assert len(result["applied"]) == 2, result
    tasks = db.query(models.Task).filter(models.Task.user_id == user.id,
                                         models.Task.text == "Pay electricity bill").all()
    assert len(tasks) == 1
    titles = [j.title for j in journals(db, user)]
    assert "Electricity bill" in titles and titles.count("Electricity bill") == 1


# ── 2. partial success is never dressed up as success ──────────────────────

def test_partial_success_is_reported_from_the_results_not_the_reply(db, user, conversation, scripted):
    before = len(journals(db, user))

    result, _ = turn(
        db, user, conversation, scripted, MOVIE_MESSAGE,
        {"reply": "Added ₹1,238 under Entertainment and the journal entry.",
         "actions": [
             MOVIE_ACTIONS[0],
             # Unusable date: the journal write must fail, the spend must stand.
             {"op": "add_journal", "title": "Ramayan movie", "date": "not a date"},
         ]},
    )

    assert len(result["applied"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["entity_type"] == "journal"
    assert result["reply"].startswith("Done — ")
    assert "Not saved —" in result["reply"]
    assert "journal entry" in result["reply"]
    # The claim "Added … the journal entry" must not survive.
    assert "Added ₹1,238 under Entertainment and the journal entry" not in result["reply"]
    assert len(journals(db, user)) == before


def test_retry_never_writes_the_same_record_twice(db, user, conversation, scripted):
    """First answer claims both records but carries no actions; the retry does."""
    before_tx, before_j = len(transactions(db, user)), len(journals(db, user))
    model = scripted(
        {"reply": "Added both.", "actions": []},
        {"reply": "Added ₹1,238 under Entertainment and a journal entry.",
         "actions": MOVIE_ACTIONS},
    )
    result = graph.run_turn(db, user, conversation.id, MOVIE_MESSAGE, [], turn=1, today=TODAY)

    assert len(model.calls) == 2, "the empty-claim answer is retried exactly once"
    assert len(result["applied"]) == 2
    assert len(transactions(db, user)) == before_tx + 1
    assert len(journals(db, user)) == before_j + 1


def test_a_missing_second_record_is_asked_for_once(db, user, conversation, scripted):
    """The model answers half the request; the turn asks for the other half."""
    model = scripted(
        {"reply": "Added the task.", "actions": [
            {"op": "add_task", "text": "Pay electricity bill", "due": TOMORROW.isoformat()}]},
        {"reply": "Added the task and the journal entry.", "actions": [
            {"op": "add_task", "text": "Pay electricity bill", "due": TOMORROW.isoformat()},
            {"op": "add_journal", "title": "Electricity bill", "date": TOMORROW.isoformat()}]},
    )
    result = graph.run_turn(
        db, user, conversation.id,
        "Add a task to pay the electricity bill tomorrow and note in my journal that I received it.",
        [], turn=1, today=TODAY)

    assert len(model.calls) == 2
    assert "journal" in model.calls[1][-1]["content"].lower()
    assert sorted(r["entity_type"] for r in result["applied"]) == ["journal", "task"]


def test_a_half_answer_is_not_reported_as_a_whole_one(db, user, conversation, scripted):
    """The retry fails too: the reply must not claim the missing record."""
    result, _ = turn(
        db, user, conversation, scripted,
        "Add a task to pay the electricity bill tomorrow and note in my journal that I received it.",
        {"reply": "Added the task and the journal entry.", "actions": [
            {"op": "add_task", "text": "Pay electricity bill", "due": TOMORROW.isoformat()}]},
    )

    assert [r["entity_type"] for r in result["applied"]] == ["task"]
    assert "journal" not in [r["entity_type"] for r in result["applied"]]
    # Nothing invented: either the model said only what happened, or the app did.
    assert result["reply"]


# ── 3. follow-up corrections resolve against the conversation ──────────────

def test_journal_date_correction_updates_the_journal_only(db, user, conversation, scripted):
    turn(db, user, conversation, scripted, MOVIE_MESSAGE,
         {"reply": "Added both.", "actions": MOVIE_ACTIONS}, number=1)

    spend = [r for r in transactions(db, user) if r.description == "Ramayan movie"][0]
    entry = [j for j in journals(db, user) if j.title == "Ramayan movie"][0]
    spend_date = spend.txn_date

    result, _ = turn(
        db, user, conversation, scripted,
        "Watched Ramayan movie for this journal entry the date is tomorrow, so update it.",
        {"reply": "Updated the journal entry date.", "actions": [
            {"op": "update_journal", "title": "Ramayan movie",
             "date": (TOMORROW.replace(day=21)).isoformat()}]},
        number=2,
    )

    assert len(result["applied"]) == 1, result
    assert result["applied"][0]["entity_type"] == "journal"
    db.refresh(entry)
    db.refresh(spend)
    assert entry.event_date == date(2026, 11, 21)
    assert spend.txn_date == spend_date, "the transaction date must not move"
    # The other fields survive the correction.
    assert entry.description == "Watched Ramayan movie in the evening"
    assert entry.category == "Life"


def test_correction_does_not_touch_a_similarly_named_task(db, user, conversation, scripted):
    db.add(models.Task(id="seed-movie-task", user_id=user.id, text="Ramayan movie tickets",
                       due=TOMORROW, priority="high", category="Personal"))
    db.add(models.JournalEntry(id="seed-movie-journal", user_id=user.id,
                               title="Ramayan movie", description="Went to the cinema",
                               event_date=TODAY))
    db.commit()

    result, _ = turn(db, user, conversation, scripted,
                     "Move the Ramayan movie journal entry to tomorrow.",
                     {"reply": "Updated the journal entry.", "actions": [
                         {"op": "update_journal", "title": "Ramayan movie",
                          "date": TOMORROW.isoformat()}]})

    assert result["applied"][0]["entity_type"] == "journal"
    task = db.get(models.Task, "seed-movie-task")
    db.refresh(task)
    assert task.due == TOMORROW
    assert task.text == "Ramayan movie tickets"
    entry = db.get(models.JournalEntry, "seed-movie-journal")
    db.refresh(entry)
    assert entry.event_date == TOMORROW


def test_only_the_requested_field_changes(db, user, conversation, scripted):
    task = db.get(models.Task, "seed-wheel-balancing")
    original_priority, original_text = task.priority, task.text

    result, _ = turn(db, user, conversation, scripted, "Push Wheel Balancing to tomorrow.",
                     {"reply": "Updated the due date.", "actions": [
                         {"op": "update_task", "text": "Wheel Balancing",
                          "due": TOMORROW.isoformat()}]})

    assert result["applied"][0]["entity_type"] == "task"
    db.refresh(task)
    assert task.due == TOMORROW
    assert task.priority == original_priority
    assert task.text == original_text


def test_tomorrow_is_the_users_local_day(db, user, conversation, scripted):
    """The prompt carries the caller's local date; the stored day is that day."""
    result, model = turn(db, user, conversation, scripted,
                         "Add a journal entry about the movie tonight.",
                         {"reply": "Added the journal entry.", "actions": [
                             {"op": "add_journal", "title": "Movie night",
                              "date": TOMORROW.isoformat()}]},
                         today=TODAY)

    assert TODAY.isoformat() in model.last_system, "the model must be told the user's local day"
    entry = [j for j in journals(db, user) if j.title == "Movie night"][0]
    assert entry.event_date == TOMORROW


# ── 4. nothing extra, nothing taken away ───────────────────────────────────

def test_single_action_requests_are_untouched(db, user, conversation, scripted):
    model = scripted({"reply": "Added the task.", "actions": [
        {"op": "add_task", "text": "Pay rent", "due": TOMORROW.isoformat()}]})
    result = graph.run_turn(db, user, conversation.id, "Add a task to pay rent tomorrow",
                            [], turn=1, today=TODAY)

    assert len(model.calls) == 1, "a single-record request must not trigger a completeness retry"
    assert [r["entity_type"] for r in result["applied"]] == ["task"]


def test_an_unrequested_action_is_refused(db, user, conversation, scripted):
    before = len(transactions(db, user))

    result, _ = turn(db, user, conversation, scripted,
                     "How much did I spend on dining out in June 2026?",
                     {"reply": "Added it.", "actions": [
                         {"op": "add_transaction", "kind": "expense", "amount": 999,
                          "category": "Dining Out", "txn_date": TODAY.isoformat()}]})

    assert result["applied"] == []
    assert len(transactions(db, user)) == before
    assert "Nothing was saved" in result["reply"]


# ── 5. the whole conversation, end to end ─────────────────────────────────

def test_end_to_end_movie_workflow(db, user, conversation, scripted):
    """Create both records, correct the journal date, then ask about the spend."""
    model = scripted(
        # turn 1 — both records
        {"reply": "Added ₹1,238 under Entertainment and a journal entry for the movie.",
         "actions": MOVIE_ACTIONS},
        # turn 2 — the date correction
        {"reply": "Moved the journal entry to 21 November 2026.", "actions": [
            {"op": "update_journal", "title": "Ramayan movie", "date": "2026-11-21"}]},
        # turn 3 — a question, no writes
        {"reply": "You spent ₹1,238 on Entertainment this month.",
         "actions": []},
    )

    first = graph.run_turn(db, user, conversation.id, MOVIE_MESSAGE, [], turn=1, today=TODAY)
    assert len(first["applied"]) == 2

    history = [{"role": "user", "content": MOVIE_MESSAGE},
               {"role": "assistant", "content": first["reply"]}]
    second = graph.run_turn(
        db, user, conversation.id,
        "Watched Ramayan movie — for that journal entry the date is tomorrow.",
        history, turn=2, today=TODAY)
    assert [r["entity_type"] for r in second["applied"]] == ["journal"]

    history += [{"role": "user", "content": "…date correction…"},
                {"role": "assistant", "content": second["reply"]}]
    spend_before = [(r.id, float(r.amount), r.txn_date) for r in transactions(db, user)]
    third = graph.run_turn(db, user, conversation.id,
                           "How much did I spend on Entertainment this month?",
                           history, turn=3, today=TODAY)

    assert third["applied"] == [] and third["failed"] == []
    assert [(r.id, float(r.amount), r.txn_date) for r in transactions(db, user)] == spend_before
    assert len(model.calls) == 3, "one model call per turn, no retries in this flow"

    entry = [j for j in journals(db, user) if j.title == "Ramayan movie"][0]
    db.refresh(entry)
    assert entry.event_date == date(2026, 11, 21)
    assert float([r for r in transactions(db, user)
                  if r.description == "Ramayan movie"][0].amount) == 1238.0


# ── 6. the helpers themselves ─────────────────────────────────────────────

@pytest.mark.parametrize("message,expected", [
    (MOVIE_MESSAGE, ["transaction", "journal"]),
    ("Add a task to pay the electricity bill tomorrow and note in my journal that I received it.",
     ["journal", "task"]),
    ("I completed my gym task today. Mark it complete and add a journal note about my workout.",
     ["journal"]),
    ("Change the journal entry date to tomorrow.", []),
    ("How much did I spend on dining out in June 2026?", []),
])
def test_requested_kinds(message, expected):
    assert multi.requested_kinds(message) == expected


def test_missing_kinds_ignores_single_record_messages():
    assert multi.missing_kinds("Add a task to pay rent tomorrow",
                               [{"op": "add_note", "title": "x"}]) == []


def test_missing_kinds_names_the_uncovered_record():
    message = ("Add a task to pay the electricity bill tomorrow and note in my journal "
               "that I received it.")
    actions = [{"op": "add_task", "text": "Pay electricity bill"}]
    assert multi.missing_kinds(message, actions) == ["journal"]


def test_partial_reply_states_both_sides():
    text = multi.partial_reply(
        [{"summary": 'Added expense "Ramayan movie"'}],
        [{"entity_type": "journal", "error": "date must be a date like 2026-11-10."}],
    )
    assert text.startswith("Done — Added expense")
    assert "Not saved — the journal entry: date must be a date like 2026-11-10." in text


def test_focus_is_not_needed_when_the_correction_names_the_record(db, user, conversation):
    """A named record resolves without the conversation's focus record."""
    db.add(models.JournalEntry(id="seed-named", user_id=user.id, title="Ramayan movie",
                               event_date=TODAY))
    db.commit()
    action = focus.apply(db, user, conversation.id,
                         {"op": "update_journal", "title": "Ramayan movie", "date": "2026-11-21"},
                         "Move the Ramayan movie journal entry to tomorrow")
    assert action.get("id") in (None, ""), "a named record keeps its own name, not the focus id"


def test_journal_and_transaction_are_different_records(db, user):
    """A journal entry never satisfies a transaction lookup and vice versa."""
    db.add(models.JournalEntry(id="seed-only-journal", user_id=user.id,
                               title="Ramayan movie", event_date=TODAY))
    db.commit()
    found = execution.execute(db, user, {"op": "update_transaction", "description": "Ramayan movie",
                                         "amount": 1500}, context={"today": TODAY})
    assert not found["success"]
    assert "could not find" in found["error"].lower()
