"""Task 30.4 — structured output must never reach the user.

The failing turn returned its whole answer *inside* the reply field:

    Moving "Submit project report" to Wednesday, 18 November 2026.

    {"reply":"Moving \\"Submit project report\\" to Wednesday, 18 November 2026.",
     "actions":[{"op":"update_task","id":"d260a16d-…","due":"2026-11-18"}]}

The strings here are copied from that message, so the tests fail if the shape
ever stops being recognised. The same turn also claimed a change it never made
(`actions` was empty), which the claim guard now catches.
"""

from __future__ import annotations

from datetime import date

from app import models
from app.agent.graph import run_turn
from app.agent.reply import claims_change, clean_reply, scrub_structured


TODAY = date(2026, 11, 14)
TASK_ID = "d260a16d-7f0a-46f1-9468-4f9beafc1bdd"

LEAKED = (
    'Moving "Submit project report" to Wednesday, 18 November 2026.\n\n'
    '{"reply":"Moving \\"Submit project report\\" to Wednesday, 18 November 2026.",'
    '"actions":[{"op":"update_task","id":"' + TASK_ID + '","due":"2026-11-18"}]}'
)
LEAKED_SENTENCE = 'Moving "Submit project report" to Wednesday, 18 November 2026.'


# ── the exact failure ──────────────────────────────────────────────────────

def test_the_leaked_turn_is_reduced_to_its_sentence():
    assert scrub_structured(LEAKED) == LEAKED_SENTENCE


def test_a_whole_json_reply_becomes_its_reply_field():
    payload = '{"reply":"Added ₹450 under Groceries.","actions":[{"op":"add_transaction","amount":450}]}'
    assert scrub_structured(payload) == "Added ₹450 under Groceries."


def test_a_broken_payload_is_cut_out_textually():
    """Unescaped quotes make it unparseable; the sentence still has to survive."""
    broken = ('Moved the task to Monday.\n\n'
              '{"reply":"Moved the task to Monday.","actions":[{"op":"update_task","due":"2026-11-16"}]')
    assert scrub_structured(broken) == "Moved the task to Monday."


def test_a_payload_in_the_middle_keeps_the_prose_around_it():
    text = ('Saved it.\n{"reply":"Saved it.","actions":[{"op":"add_task","text":"x"}]}\n'
            'Anything else?')
    assert scrub_structured(text) == "Saved it.\n\nAnything else?"


def test_a_reply_that_is_only_a_payload_becomes_empty():
    assert scrub_structured('{"actions":[{"op":"delete_task","id":"abc"}]}') == ""
    assert scrub_structured('{"reply":"","actions":[]}') == ""


# ── nothing else changes ───────────────────────────────────────────────────

def test_ordinary_replies_survive_untouched():
    for text in (
        "You spent ₹12,727.62 this month, across 9 categories.",
        'The task "Submit project report" is due Monday.',
        "Braces like {this} are fine when they are not a payload.",
        "Moved on to the next point — nothing else needed.",
    ):
        assert scrub_structured(text) == text


def test_clean_reply_still_drops_internal_ids():
    cleaned = clean_reply("Updated the task. The task id 757 belongs to you.")
    assert "757" not in cleaned
    assert "Updated the task." in cleaned


def test_clean_reply_scrubs_before_it_looks_for_ids():
    """The id inside the payload must not survive as a sentence."""
    cleaned = clean_reply(LEAKED, applied=[{"summary": "Updated task x"}])
    assert cleaned == LEAKED_SENTENCE
    assert '"op"' not in cleaned and "actions" not in cleaned


# ── the claim guard: a move that never happened is not reported as done ────

def test_a_claimed_move_with_no_action_is_a_claim():
    assert claims_change('Moving "Submit project report" to Wednesday, 18 November 2026.')
    assert claims_change("I've moved the task to Monday.")
    assert claims_change("Rescheduled to Friday.")


def test_advice_and_questions_are_not_claims():
    assert not claims_change("Should you move the task to Monday?")
    assert not claims_change("You could move it, but nothing was saved.")
    assert not claims_change("Moving averages smooth a noisy month.")


def test_a_leaking_turn_with_no_action_is_reported_as_nothing_saved(db, user, conversation, scripted):
    """End to end: the model leaks JSON and writes nothing — say so."""
    model = scripted({"reply": LEAKED, "actions": []})
    result = run_turn(db, user, conversation.id, "Change its due date to Wednesday.",
                      [], turn=1, today=TODAY)

    reply = result["reply"]
    assert "{" not in reply and '"op"' not in reply
    assert "actions" not in reply
    assert result["applied"] == []
    assert "Nothing was saved" in reply or "not recorded" in reply
    assert len(model.calls) == 2, "the empty-claim answer is retried once"


def test_a_verified_turn_reports_from_the_results(db, user, conversation, scripted):
    """The same leak, but the action ran: the reply is clean and confirmed."""
    task = models.Task(id="seed-shift-me", user_id=user.id, text="Shift me",
                       due=date(2026, 11, 20), priority="medium", category="Work")
    db.add(task)
    db.commit()

    scripted({"reply": LEAKED,
              "actions": [{"op": "update_task", "id": "seed-shift-me", "due": "2026-11-18"}]})
    result = run_turn(db, user, conversation.id,
                      "Move the Shift me task 'Shift me' to Wednesday", [], turn=1, today=TODAY)

    assert [r["operation"] for r in result["applied"]] == ["update_task"], result
    db.refresh(task)
    assert task.due == date(2026, 11, 18)
    reply = result["reply"]
    assert "{" not in reply and '"op"' not in reply
    assert LEAKED_SENTENCE in reply or "Done —" in reply


# ── the leak is not specific to task updates ───────────────────────────────

def test_a_creation_turn_that_leaks_json_still_applies_and_reads_clean(db, user, conversation, scripted):
    """Two records, a leaking reply: both writes land, the text is clean."""
    leaked = ('Added ₹1,238 under Entertainment and a journal entry.\n\n'
              '{"reply":"Added ₹1,238 under Entertainment and a journal entry.",'
              '"actions":[{"op":"add_transaction","amount":1238,"category":"Entertainment"},'
              '{"op":"add_journal","title":"Ramayan movie","date":"2026-11-14"}]}')
    scripted({"reply": leaked, "actions": [
        {"op": "add_transaction", "kind": "expense", "amount": 1238,
         "category": "Entertainment", "description": "Ramayan movie",
         "txn_date": "2026-11-14"},
        {"op": "add_journal", "title": "Ramayan movie", "date": "2026-11-14"},
    ]})
    result = run_turn(db, user, conversation.id,
                      "Add ₹1,238 for Ramayan movie in Entertainment and a journal entry.",
                      [], turn=1, today=TODAY)

    assert len(result["applied"]) == 2, result
    reply = result["reply"]
    assert '"op"' not in reply and '"actions"' not in reply and "{" not in reply
    assert reply == "Added ₹1,238 under Entertainment and a journal entry."


def test_a_journal_update_that_leaks_json_reads_clean(db, user, conversation, scripted):
    db.add(models.JournalEntry(id="seed-j1", user_id=user.id, title="Ramayan movie",
                               description="Watched it", event_date=date(2026, 11, 13)))
    db.commit()

    leaked = ('Moved the journal entry to 15 November 2026.\n'
              '{"reply":"Moved the journal entry to 15 November 2026.",'
              '"actions":[{"op":"update_journal","id":"seed-j1","date":"2026-11-15"}]}')
    scripted({"reply": leaked, "actions": [
        {"op": "update_journal", "id": "seed-j1", "date": "2026-11-15"}]})
    result = run_turn(db, user, conversation.id,
                      "Move the Ramayan movie journal entry to Sunday", [], turn=1, today=TODAY)

    assert [r["operation"] for r in result["applied"]] == ["update_journal"], result
    reply = result["reply"]
    assert "{" not in reply and '"op"' not in reply
    entry = db.get(models.JournalEntry, "seed-j1")
    db.refresh(entry)
    assert entry.event_date == date(2026, 11, 15)
