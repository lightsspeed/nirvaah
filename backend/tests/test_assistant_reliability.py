"""Regression suite for the assistant's reliability contract.

Every scenario from the audit brief, run against a throwaway SQLite database and
a scripted model — no network, no real records.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func

from app import models
from app.agent import execution, graph
from app.agent import resolve as resolver


def run(db, user, conversation, scripted, message, model_reply, *, turn=1, history=None):
    model = scripted(model_reply)
    result = graph.run_turn(db, user, conversation.id, message, history or [], turn=turn)
    return result, model


def tasks(db, user):
    db.expire_all()
    return (db.query(models.Task)
            .filter(models.Task.user_id == user.id)
            .order_by(models.Task.text).all())


# ── A. two tasks in one message ─────────────────────────────────────────────

def test_a_create_two_tasks(db, user, conversation, scripted):
    reply = {
        "reply": "Adding both for 14 November 2026.",
        "actions": [
            {"op": "add_task", "text": "Pay electricity bills", "due": "2026-11-14"},
            {"op": "add_task", "text": "Pay maintenance", "due": "2026-11-14"},
        ],
    }
    result, _ = run(db, user, conversation, scripted,
                    "add two tasks pay electricity bills and pay maintenance - 14th Nov", reply)

    assert [a["operation"] for a in result["applied"]] == ["add_task", "add_task"]
    assert all(a["verified"] for a in result["applied"])
    assert result["failed"] == []

    rows = [t for t in tasks(db, user) if t.text in ("Pay electricity bills", "Pay maintenance")]
    assert len(rows) == 2, "exactly two records, no duplicates"
    assert all(t.due == date(2026, 11, 14) for t in rows)
    assert {str(t.id) for t in rows} == {a["entity_id"] for a in result["applied"]}


def test_a_retry_does_not_duplicate(db, user, conversation, scripted):
    reply = {
        "reply": "Added.",
        "actions": [{"op": "add_task", "text": "Pay rent", "due": "2026-11-14"}],
    }
    run(db, user, conversation, scripted, "add a task to pay rent on 14 nov", reply)
    before = len(tasks(db, user))
    run(db, user, conversation, scripted, "add a task to pay rent on 14 nov", reply, turn=2)
    assert len(tasks(db, user)) == before + 1, "a second request is a second task, not a silent dupe"


# ── B. reschedule by name ───────────────────────────────────────────────────

def test_b_reschedule_updates_the_right_task(db, user, conversation, scripted):
    reply = {"reply": "Moving it.", "actions": [
        {"op": "update_task", "text": "Wheel Balancing", "due": "2026-11-21"}]}
    result, _ = run(db, user, conversation, scripted, "Reschedule Wheel Balancing to 21 November", reply)

    applied = result["applied"][0]
    assert applied["verified"] is True
    assert applied["changes"]["due"] == {"before": "2026-11-15", "after": "2026-11-21"}

    db.expire_all()
    row = db.query(models.Task).filter(models.Task.text == "Wheel Balancing").one()
    assert row.due == date(2026, 11, 21)


# ── C. follow-up with a pronoun ─────────────────────────────────────────────

def test_c_followup_updates_the_focused_task(db, user, conversation, scripted):
    create = {"reply": "Created.", "actions": [
        {"op": "add_task", "text": "Car Wash", "due": "2026-11-16"}]}
    first, _ = run(db, user, conversation, scripted, "create a task called Car Wash", create)
    created_id = first["applied"][0]["entity_id"]

    update = {"reply": "Set to high.", "actions": [{"op": "update_task", "priority": "high"}]}
    second, model = run(db, user, conversation, scripted, "Make it high priority", update, turn=2)

    assert second["applied"][0]["entity_id"] == created_id, "the pronoun resolved to the same record"
    assert "CURRENT FOCUS" in model.last_system
    db.expire_all()
    row = db.get(models.Task, created_id)
    assert row.priority == "high"
    assert len([t for t in tasks(db, user) if t.text == "Car Wash"]) == 1


# ── D. category analytics for a named month ─────────────────────────────────

def test_d_category_month_uses_the_database(db, user, conversation, scripted):
    reply = {"reply": "You spent ₹2,144.62 on Dining Out in June 2026.", "actions": []}
    result, model = run(db, user, conversation, scripted,
                        "How much did I spend on Dining Out in June?", reply, turn=3)

    assert "VERIFIED ANALYTICS (intent: category_month)" in model.last_system
    assert '"total": 2144.62' in model.last_system
    assert '"month": "2026-06"' in model.last_system
    assert result["applied"] == []


def test_d_category_name_is_fuzzy_matched(db, user, conversation, scripted):
    reply = {"reply": "ok", "actions": []}
    _, model = run(db, user, conversation, scripted,
                   "how much did i spend on dining out in june", reply, turn=2)
    assert '"categories": ["Dining Out"]' in model.last_system


# ── E. the month with the highest spend in a category ───────────────────────

def test_e_max_month_for_category(db, user, conversation, scripted):
    reply = {"reply": "May 2026, ₹2,867.", "actions": []}
    _, model = run(db, user, conversation, scripted,
                   "Which month has the maximum spending on Office Eats?", reply, turn=2)

    system = model.last_system
    assert "VERIFIED ANALYTICS (intent: category_series)" in system
    assert '"max_month": {"month": "2026-05"' in system
    assert '"amount"' in system or '"total": 2867.0' in system


# ── F. journal entry is not a task ──────────────────────────────────────────

def test_f_journal_entry_is_not_completable(db, user, conversation, scripted):
    reply = {"reply": "Marking that done.", "actions": [
        {"op": "update_task", "text": "Leave office at 7 PM", "done": True}]}
    result, _ = run(db, user, conversation, scripted, "Leave office at 7 PM is done.", reply)

    assert result["applied"] == []
    assert result["failed"], "the action must fail, not silently retarget"
    assert "journal entry" in result["reply"].lower()
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Leave office at 7 PM").count() == 0


# ── G. never claim a write that did not happen ──────────────────────────────

def test_g_false_success_is_blocked(db, user, conversation, scripted):
    lie = {"reply": "Added both tasks for 14 November 2026.", "actions": []}
    before = len(tasks(db, user))
    result, model = run(db, user, conversation, scripted,
                        "add two tasks pay electricity bills and pay maintenance", lie)

    assert len(model.calls) == 2, "the claim triggers exactly one retry"
    assert result["applied"] == []
    assert "nothing was saved" in result["reply"].lower()
    assert len(tasks(db, user)) == before


def test_g_claim_with_retry_succeeds(db, user, conversation, scripted):
    lie = {"reply": "Added both tasks.", "actions": []}
    truth = {"reply": "Adding them now.", "actions": [
        {"op": "add_task", "text": "Pay electricity bills", "due": "2026-11-14"},
        {"op": "add_task", "text": "Pay maintenance", "due": "2026-11-14"}]}
    model = scripted(lie, truth)
    result = graph.run_turn(db, user, conversation.id, "add two tasks …", [], turn=1)

    assert len(model.calls) == 2
    assert len(result["applied"]) == 2
    assert all(a["verified"] for a in result["applied"])


# ── H. a month with no transactions is not ₹0 ───────────────────────────────

def test_h_empty_month_is_reported_as_missing_not_zero(db, user, conversation, scripted):
    reply = {"reply": "You spent ₹0 on Dining Out in July 2026.", "actions": []}
    result, model = run(db, user, conversation, scripted,
                        "How much did I spend on Dining Out in July 2026?", reply, turn=2)

    assert "STATUS: no_data_for_category" in model.last_system
    lowered = result["reply"].lower()
    assert "₹0" not in result["reply"]
    assert "no spending" in lowered or "missing" in lowered or "no transactions" in lowered


# ── I. context survives a follow-up, without duplicates ─────────────────────

def test_i_due_date_followup(db, user, conversation, scripted):
    create = {"reply": "Created.", "actions": [
        {"op": "add_task", "text": "Water the plants", "due": "2026-11-12"}]}
    first, _ = run(db, user, conversation, scripted, "create a task called Water the plants", create)
    task_id = first["applied"][0]["entity_id"]

    update = {"reply": "Moving it.", "actions": [
        {"op": "update_task", "due": "2026-11-16", "text": ""}]}
    second, _ = run(db, user, conversation, scripted, "change its due date to Sunday", update, turn=2)

    assert second["applied"][0]["entity_id"] == task_id
    db.expire_all()
    assert db.get(models.Task, task_id).due == date(2026, 11, 16)
    assert len([t for t in tasks(db, user) if t.text == "Water the plants"]) == 1


# ── J. no stale operation metadata on a later turn ──────────────────────────

def test_j_question_turn_reports_no_changes(db, user, conversation, scripted):
    create = {"reply": "Saved.", "actions": [
        {"op": "add_task", "text": "Pay electricity bills", "due": "2026-11-14"},
        {"op": "add_task", "text": "Pay maintenance", "due": "2026-11-14"}]}
    first, _ = run(db, user, conversation, scripted, "add two tasks", create)
    assert len(first["applied"]) == 2

    thanks = {"reply": "Glad it is in place.", "actions": []}
    second, _ = run(db, user, conversation, scripted, "thanks", thanks, turn=2)
    assert second["applied"] == []
    assert second["pending"] == []
    assert second["failed"] == []


# ── K. an ambiguous name is a question, not a guess ─────────────────────────

def test_k_ambiguous_target_asks_instead_of_updating(db, user, conversation, scripted):
    reply = {"reply": "Rescheduling.", "actions": [
        {"op": "update_task", "text": "servicing", "due": "2026-11-21"}]}
    result, _ = run(db, user, conversation, scripted, "Reschedule my servicing task", reply)

    assert result["applied"] == []
    assert "which one" in result["reply"].lower()
    db.expire_all()
    due_dates = {t.due for t in tasks(db, user) if "Servicing" in t.text}
    assert due_dates == {date(2026, 11, 15)}, "no arbitrary record was touched"


def test_k_unique_name_still_resolves(db, user, conversation, scripted):
    reply = {"reply": "Moved.", "actions": [
        {"op": "update_task", "text": "Scooty Servicing", "due": "2026-11-21"}]}
    result, _ = run(db, user, conversation, scripted, "Reschedule Scooty Servicing to 21 November", reply)
    assert result["applied"], result["failed"]
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Scooty Servicing").one().due == date(2026, 11, 21)


# ── L. a failed write is reported as a failure ──────────────────────────────

def test_l_commit_failure_is_honest(db, user, conversation, scripted, monkeypatch):
    monkeypatch.setattr(execution, "_commit",
                        lambda db, op, kind: "The database refused the change — nothing was saved.")
    reply = {"reply": "Added the task.", "actions": [
        {"op": "add_task", "text": "Pay electricity bills", "due": "2026-11-14"}]}
    before = len(tasks(db, user))
    result, _ = run(db, user, conversation, scripted, "add a task to pay electricity bills", reply)

    assert result["applied"] == []
    assert "database refused" in result["reply"].lower()
    assert len(tasks(db, user)) == before


def test_l_verification_failure_is_honest(db, user, conversation, scripted, monkeypatch):
    """The commit "succeeds" but the row does not come back as asked."""
    real_read = execution._read_back
    monkeypatch.setattr(execution, "_read_back", lambda db, model, pk: None)
    reply = {"reply": "Updated.", "actions": [
        {"op": "update_task", "text": "Wheel Balancing", "due": "2026-11-21"}]}
    result, _ = run(db, user, conversation, scripted, "Reschedule Wheel Balancing to 21 November", reply)

    assert result["applied"] == []
    assert "persist" in result["reply"].lower() or "missing" in result["reply"].lower()
    monkeypatch.setattr(execution, "_read_back", real_read)


# ── deletes: proposal first, then a verified removal ────────────────────────

def test_delete_needs_confirmation_then_verifies(db, user, conversation, scripted):
    reply = {"reply": "I can remove that.", "actions": [
        {"op": "delete_task", "text": "Scooty Servicing"}]}
    result, _ = run(db, user, conversation, scripted, "Delete the Scooty Servicing task", reply)

    assert result["pending"], "a delete is only proposed"
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Scooty Servicing").count() == 1

    confirmed = execution.execute(db, user, dict(result["pending"][0], pending=False))
    assert confirmed["success"] and confirmed["verified"]
    db.expire_all()
    assert db.query(models.Task).filter(models.Task.text == "Scooty Servicing").count() == 0


# ── resolver unit behaviour ────────────────────────────────────────────────

def test_resolver_prefers_exact_over_partial(db, user):
    found = resolver.resolve(db, user, "task", query="Wheel Balancing")
    assert found.ok and found.row.text == "Wheel Balancing"


def test_resolver_reports_not_found(db, user):
    found = resolver.resolve(db, user, "task", query="Renew passport")
    assert found.status == "not_found"
    assert "could not find" in found.message


def test_resolver_ignores_request_words(db, user):
    """"reschedule my servicing task" must not match on 'task'."""
    found = resolver.resolve(db, user, "task", query="reschedule my servicing task")
    assert found.status == "ambiguous"
    assert len(found.candidates) == 2


def test_analytics_distinguish_zero_from_missing(db, user):
    from app.agent import analytics

    june = analytics.category_month(db, user, "Office Eats", "2026-06")
    assert june["status"] == "no_data_for_category", "the category exists, the month is empty"

    unknown = analytics.category_month(db, user, "Yachts", "2026-06")
    assert unknown["status"] == "unknown_category"

    peak = analytics.category_series(db, user, "Office Eats")
    assert peak["max_month"]["month"] == "2026-05"


def test_planner_resolves_relative_months():
    from datetime import date as d

    from app.agent import planner

    today = d(2026, 11, 12)
    assert planner.resolve_month("in June", today) == "2026-06"
    assert planner.resolve_month("June 2025", today) == "2025-06"
    assert planner.resolve_month("last month", today) == "2026-10"
    assert planner.resolve_month("this month", today) == "2026-11"
    assert planner.resolve_month("in February", today) == "2026-02"
    assert planner.resolve_month("no month here", today) is None


def test_totals_still_add_up(db, user):
    from app.agent import analytics

    june = analytics.summary(db, user, "2026-06")
    assert june["income"] == 90000.00
    assert june["expense"] == round(1444.62 + 700 + 900, 2)
    assert june["savings"] == round(90000 - 3044.62, 2)


# ── an invented category is named, not answered with a figure ───────────────

def test_unknown_category_is_not_a_zero(db, user, conversation, scripted):
    reply = {"reply": "You spent ₹0 on Yachts in June 2026.", "actions": []}
    result, model = run(db, user, conversation, scripted,
                        "How much did I spend on Yachts in June 2026?", reply, turn=2)

    assert "STATUS: unknown_category" in model.last_system
    assert "₹0" not in result["reply"]
    assert "yachts" in result["reply"].lower()


def test_real_phrase_in_a_description_is_not_called_unknown(db, user, conversation, scripted):
    """'pizza' appears in descriptions, so it must not be reported as missing."""
    reply = {"reply": "Here is what I found.", "actions": []}
    _, model = run(db, user, conversation, scripted,
                   "How much did I spend on pizza in June 2026?", reply, turn=2)
    assert "STATUS: unknown_category" not in model.last_system
