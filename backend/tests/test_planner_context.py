"""Conversation continuity: the thread keeps its filters, never its figures.

The acceptance conversation is the test: Groceries and April are established in
turn 1, and turns 2-5 change one dimension at a time without the user repeating
themselves. Every figure here is recomputed from SQL on the turn that quotes it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app import models
from app.agent import graph, planner


TODAY = date(2026, 11, 13)
APRIL_TOTAL = Decimal("7897.00")


@pytest.fixture()
def groceries(db, user):
    """38 April grocery rows (7,897.00), a May month, Fuel in April, power in May."""
    amounts = [Decimal("207.82")] * 37 + [APRIL_TOTAL - Decimal("207.82") * 37]
    for index, amount in enumerate(amounts):
        db.add(models.Transaction(
            user_id=user.id, kind="expense", amount=amount, category="Groceries",
            description="BigBasket", payment_method="SBI",
            txn_date=date(2026, 4, 1) + timedelta(days=index % 30),
        ))
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=Decimal("2000.00"),
                              category="Fuel", description="HP Petrol", payment_method="SBI",
                              txn_date=date(2026, 4, 18)))
    for day, amount in ((3, Decimal("300.00")), (17, Decimal("400.00")), (28, Decimal("200.00"))):
        db.add(models.Transaction(user_id=user.id, kind="expense", amount=amount,
                                  category="Groceries", description="More Supermarket",
                                  payment_method="UPI", txn_date=date(2026, 5, day)))
    db.add(models.Transaction(user_id=user.id, kind="expense", amount=Decimal("1500.00"),
                              category="Electricity", description="BESCOM", payment_method="UPI",
                              txn_date=date(2026, 5, 9)))
    db.commit()
    return user


def context(category="Groceries", month="2026-04", kind="expense", turn=1):
    return {"intent": "category_series", "category": category, "month": month, "kind": kind,
            "comparison_target": None, "turn": turn, "updated_at": "2026-11-13T10:00:00Z"}


# ── A. the resolution table, as a pure function ────────────────────────────

@pytest.mark.parametrize("message,expected", [
    ("Why was April highest?", ("Groceries", "2026-04", True)),
    ("What about May?", ("Groceries", "2026-05", True)),
    ("Show me those transactions", ("Groceries", "2026-04", True)),
    ("No, I meant fuel", ("Fuel", "2026-04", True)),
    ("What about fuel?", ("Fuel", "2026-04", True)),
    ("What is my electricity bill?", ("Electricity", None, False)),
    ("Which merchant contributed most?", ("Groceries", "2026-04", True)),
])
def test_the_resolution_table(db, groceries, message, expected):
    pool = ["Groceries", "Fuel", "Electricity"]
    resolved = planner.resolve_followup(message, context(), TODAY, pool=pool, turn=2)

    assert (resolved["category"], resolved["month"], resolved["followup"]) == expected
    assert resolved["ambiguous"] is False


def test_a_reference_with_no_context_asks_instead_of_guessing():
    resolved = planner.resolve_followup("Show me those transactions", None, TODAY)

    assert resolved["ambiguous"] is True
    assert "which transactions" in resolved["question"].lower()


def test_an_explicit_category_and_month_start_a_new_question():
    resolved = planner.resolve_followup("List groceries in June", context(), TODAY,
                                        pool=["Groceries"], turn=2)

    assert (resolved["category"], resolved["month"], resolved["followup"]) == ("Groceries", "2026-06", False)


def test_context_expires_after_the_ttl():
    old = context(turn=1)
    fresh = planner.resolve_followup("Why was April highest?", old, TODAY,
                                     pool=["Groceries"], turn=1 + planner.CONTEXT_TTL_TURNS)
    stale = planner.resolve_followup("Why was April highest?", old, TODAY,
                                     pool=["Groceries"], turn=2 + planner.CONTEXT_TTL_TURNS)

    assert fresh["category"] == "Groceries" and fresh["expired"] is False
    assert stale["category"] is None and stale["expired"] is True


def test_overall_clears_the_thread():
    resolved = planner.resolve_followup("How much did I spend overall?", context(), TODAY,
                                        pool=["Groceries"], turn=2)

    assert resolved["reset"] is True
    assert resolved["category"] is None


# ── B. the planner uses the resolved filters ───────────────────────────────

def test_why_was_april_highest_gets_april_groceries(db, groceries):
    analysis = planner.analyse(db, groceries, "Why was April highest?", today=TODAY,
                               context=context(), turn=2)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["categories"] == ["Groceries"]
    assert analysis["facts"]["month"] == "2026-04"
    assert analysis["facts"]["count"] == 38
    assert analysis["facts"]["total"] == 7897.0


def test_what_about_may_keeps_groceries_and_moves_the_month(db, groceries):
    analysis = planner.analyse(db, groceries, "What about May?", today=TODAY,
                               context=context(), turn=2)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["categories"] == ["Groceries"]
    assert analysis["facts"]["month"] == "2026-05"
    assert analysis["facts"]["count"] == 3
    assert analysis["facts"]["total"] == 900.0


def test_those_transactions_means_the_previous_filters(db, groceries):
    analysis = planner.analyse(db, groceries, "Show me those transactions", today=TODAY,
                               context=context(), turn=4)

    assert analysis["intent"] == "list_transactions"
    facts = analysis["facts"]
    assert (facts["category"], facts["month"], facts["count"]) == ("Groceries", "2026-04", 38)
    assert len(facts["transactions"]) == 38


def test_a_correction_replaces_only_the_category(db, groceries):
    analysis = planner.analyse(db, groceries, "No, I meant fuel", today=TODAY,
                               context=context(), turn=3)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["categories"] == ["Fuel"]
    assert analysis["facts"]["month"] == "2026-04"
    assert analysis["facts"]["total"] == 2000.0


def test_what_about_a_named_category_keeps_the_period(db, groceries):
    analysis = planner.analyse(db, groceries, "What about fuel?", today=TODAY,
                               context=context(), turn=3)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["categories"] == ["Fuel"]
    assert analysis["facts"]["month"] == "2026-04"


def test_a_new_topic_does_not_inherit_groceries(db, groceries):
    analysis = planner.analyse(db, groceries, "What is my electricity bill?", today=TODAY,
                               context=context(), turn=3)

    assert analysis["facts"]["categories"] == ["Electricity"]
    assert analysis["context"]["month"] is None
    assert analysis["context"]["category"] == "Electricity"


def test_merchants_answer_for_the_inherited_period(db, groceries):
    analysis = planner.analyse(db, groceries, "Which merchant contributed most?", today=TODAY,
                               context=context(month="2026-05", turn=4), turn=5)

    assert analysis["intent"] == "merchants"
    assert analysis["facts"]["month"] == "2026-05"
    assert "More Supermarket" in {m["merchant"] for m in analysis["facts"]["merchants"]}


def test_aggregate_routing_is_unchanged_by_context(db, groceries):
    analysis = planner.analyse(db, groceries, "How much did I spend on groceries in April?",
                               today=TODAY, context=context(), turn=2)

    assert analysis["intent"] == "category_month"
    assert "transactions" not in analysis["facts"]


# ── C. across separate HTTP requests in one conversation ───────────────────

@pytest.fixture()
def client(db, user):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app
    from app.security import get_current_user

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _conversation(client, title="thread"):
    response = client.post("/api/chat/conversations", json={"title": title})
    assert response.status_code == 200
    return response.json()["id"]


def _ask(client, conversation_id, message):
    response = client.post(f"/api/chat/conversations/{conversation_id}/messages",
                           json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_acceptance_conversation_survives_separate_requests(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)

    _ask(client, conversation_id, "How much are we spending on groceries on average?")
    assert "VERIFIED ANALYTICS (intent: category_series)" in model.last_system

    _ask(client, conversation_id, "Why was April highest?")
    assert "VERIFIED ANALYTICS (intent: category_month)" in model.last_system
    assert '"category": "Groceries"' in model.last_system
    assert '"month": "2026-04"' in model.last_system
    assert '"total": 7897.0' in model.last_system

    _ask(client, conversation_id, "List down the groceries spends of April.")
    assert "VERIFIED ANALYTICS (intent: list_transactions)" in model.last_system
    assert '"transactions": [' in model.last_system

    _ask(client, conversation_id, "What about May?")
    # The previous answer was a listing, so May is a listing too (Task 27.5.1 F3).
    assert "VERIFIED ANALYTICS (intent: list_transactions)" in model.last_system
    assert '"month": "2026-05"' in model.last_system
    assert '"count": 3' in model.last_system

    _ask(client, conversation_id, "Which merchant contributed most?")
    assert "VERIFIED ANALYTICS (intent: merchants)" in model.last_system
    assert '"month": "2026-05"' in model.last_system


def test_the_filters_are_persisted_but_not_the_figures(db, groceries, client, scripted):
    scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")

    rows = (db.query(models.ChatMessage)
            .filter(models.ChatMessage.conversation_id == conversation_id,
                    models.ChatMessage.role == "assistant")
            .all())
    meta = json.loads(rows[-1].meta)
    stored = meta["analytics"]

    assert set(stored) == {"intent", "category", "month", "kind", "comparison_target", "turn", "updated_at"}
    assert stored["category"] == "Groceries" and stored["intent"] == "category_series"
    assert "total" not in stored and "transactions" not in stored


def test_context_after_a_first_turn_is_stored_and_reused(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")

    rows = (db.query(models.ChatMessage)
            .filter(models.ChatMessage.conversation_id == conversation_id,
                    models.ChatMessage.role == "assistant")
            .all())
    stored = json.loads(rows[-1].meta)["analytics"]
    assert stored["category"] == "Groceries" and stored["intent"] == "category_series"

    _ask(client, conversation_id, "Why was April highest?")
    assert "THREAD CONTEXT: category=Groceries" in model.last_system


def test_an_unresolved_reference_asks_before_answering(db, groceries, client, scripted):
    model = scripted({"reply": "Here are some numbers.", "actions": []})
    conversation_id = _conversation(client)

    reply = _ask(client, conversation_id, "Show me those transactions")

    assert "which transactions do you mean" in reply["content"].lower()
    assert "STATUS: ambiguous" in model.last_system
    assert "VERIFIED ANALYTICS (intent:" in model.last_system


def test_conversations_do_not_share_context(db, groceries, client, scripted):
    scripted({"reply": "ok", "actions": []})
    first = _conversation(client, "first")
    _ask(client, first, "How much are we spending on groceries on average?")

    model = scripted({"reply": "ok", "actions": []})
    second = _conversation(client, "second")
    _ask(client, second, "Why was April highest?")

    assert "VERIFIED ANALYTICS (intent:" not in model.last_system
    assert "THREAD CONTEXT: category=" not in model.last_system


def test_old_messages_without_analytics_metadata_are_ignored(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    db.add(models.ChatMessage(conversation_id=conversation_id, user_id=groceries.id,
                              role="assistant", content="old reply", meta="{}"))
    db.commit()

    _ask(client, conversation_id, "Why was April highest?")

    assert "VERIFIED ANALYTICS (intent:" not in model.last_system


# ── D. freshness and write safety ──────────────────────────────────────────

def test_a_previous_total_is_never_reused(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")

    victim = (db.query(models.Transaction)
              .filter(models.Transaction.user_id == groceries.id,
                      models.Transaction.category == "Groceries",
                      models.Transaction.txn_date >= date(2026, 4, 1),
                      models.Transaction.txn_date < date(2026, 5, 1))
              .first())
    expected = Decimal("7897.00") - Decimal(str(victim.amount))
    db.delete(victim)
    db.commit()

    _ask(client, conversation_id, "Why was April highest?")
    assert f'"total": {json.dumps(float(expected))}' in model.last_system


def test_analytics_context_cannot_delete_anything(db, groceries, client, scripted):
    scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")
    before = db.query(models.Transaction).count()

    # The model asks to delete "those" without naming a record; the context must not stand in for one.
    scripted({"reply": "Removing those.", "actions": [{"op": "delete_transaction"}]})
    reply = _ask(client, conversation_id, "Delete those transactions")

    db.expire_all()
    assert db.query(models.Transaction).count() == before
    assert reply["content"]


def test_a_clarification_turn_executes_nothing(db, user, conversation, scripted):
    scripted({"reply": "Deleting now.", "actions": [{"op": "delete_transaction", "id": "anything"}]})
    before = db.query(models.Transaction).count()

    result = graph.run_turn(db, user, conversation.id, "Show me those transactions", [], turn=1)

    db.expire_all()
    assert result["applied"] == [] and result["pending"] == []
    assert db.query(models.Transaction).count() == before
    assert "which transactions do you mean" in result["reply"].lower()


# ── E. hardening (Task 27.2.1) ─────────────────────────────────────────────
# H2: a pronoun-only write is a write, not an analytics question.

@pytest.mark.parametrize("message", [
    "it is done", "that's done", "finished it", "cancel it", "it's paid",
])
def test_pronoun_only_writes_are_executed_not_clarified(db, user, conversation, scripted, message):
    create = {"reply": "Created.", "actions": [
        {"op": "add_task", "text": "Water the plants", "due": "2026-11-12"}]}
    scripted(create)
    first = graph.run_turn(db, user, conversation.id, "create a task called Water the plants", [], turn=1)
    task_id = first["applied"][0]["entity_id"]

    scripted({"reply": "Done.", "actions": [{"op": "update_task", "due": "2026-11-16"}]})
    # The action carries no id: only chat_focus can supply one.
    second = graph.run_turn(db, user, conversation.id, message, [], turn=2)

    assert second["applied"], f"{message!r} was not executed: {second['reply']!r}"
    assert second["applied"][0]["entity_id"] == task_id
    db.expire_all()
    assert db.get(models.Task, task_id).due == date(2026, 11, 16)
    assert "which transactions do you mean" not in second["reply"].lower()


def test_an_analytics_reference_without_context_still_asks():
    resolved = planner.resolve_followup("Show me those transactions", None, TODAY)

    assert resolved["ambiguous"] is True


# H1: an explicit reset wins, and it survives the graph and the next request.

def test_overall_clears_the_graph_state(db, groceries, conversation, scripted):
    scripted({"reply": "ok", "actions": []})

    result = graph.run_turn(db, groceries, conversation.id, "How much did I spend overall?", [],
                            turn=2, chat_context=context())

    assert result["chat_context"] == {}
    assert "THREAD CONTEXT: " not in result["system"]


def test_overall_persists_null_and_does_not_resurrect(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")

    _ask(client, conversation_id, "How much did I spend overall?")
    assert "THREAD CONTEXT: " not in model.last_system
    rows = (db.query(models.ChatMessage)
            .filter(models.ChatMessage.conversation_id == conversation_id,
                    models.ChatMessage.role == "assistant")
            .order_by(models.ChatMessage.id).all())
    assert json.loads(rows[-1].meta)["analytics"] is None

    _ask(client, conversation_id, "Why was April highest?")
    assert "VERIFIED ANALYTICS (intent:" not in model.last_system


# M1: merchant results say they cover every category.

def test_merchants_disclose_their_scope(db, groceries, conversation, scripted):
    scripted({"reply": "ok", "actions": []})

    result = graph.run_turn(db, groceries, conversation.id, "Which merchant contributed most?", [],
                            turn=2, chat_context=context())
    facts = result["analytics"]["facts"]

    # The thread carries Groceries, so the merchant query is filtered to it and says so.
    assert facts["scope"] == "Groceries"
    assert facts["category"] == "Groceries"
    assert '"scope": "Groceries"' in result["system"]
    assert "THREAD CONTEXT: category=Groceries month=2026-04" in result["system"]


def test_merchants_without_a_thread_report_all_categories(db, groceries):
    analysis = planner.analyse(db, groceries, "Which merchant contributed most?", today=TODAY)

    assert analysis["facts"]["scope"] == "all categories"
    assert analysis["facts"]["category"] is None


# M2: "all expenses" steps out of the category but keeps the month.

@pytest.mark.parametrize("message,month", [
    ("Show all expenses from September.", "2026-09"),
    ("List all my transactions in April.", "2026-04"),
    ("Show all spends in May", "2026-05"),
    ("Show all spending in June", "2026-06"),
    ("Show all payments in July", "2026-07"),
    ("Show me everything from September.", "2026-09"),
])
def test_all_scope_clears_the_category_and_keeps_the_month(db, groceries, message, month):
    resolved = planner.resolve_followup(message, context(), TODAY, pool=["Groceries"], turn=2)

    assert resolved["category"] is None
    assert resolved["month"] == month
    assert resolved["all_categories"] is True
    # All categories is a change of scope, not a reset: the thread keeps going
    # (Task 27.5.3 F6), so a later "what about June?" is still a follow-up.
    assert resolved["reset"] is False


@pytest.mark.parametrize("message", [
    "How much did I spend overall?",
    "What did I spend in total?",
    "Show me everything altogether.",
])
def test_an_all_time_request_resets_the_thread(db, groceries, message):
    resolved = planner.resolve_followup(message, context(), TODAY, pool=["Groceries"], turn=2)

    assert resolved["reset"] is True
    assert resolved["all_categories"] is False
    assert resolved["category"] is None and resolved["month"] is None


def test_all_expenses_lists_every_category(db, groceries):
    analysis = planner.analyse(db, groceries, "Show all expenses from September.", today=TODAY,
                               context=context(), turn=2)

    assert analysis["intent"] == "list_transactions"
    assert analysis["facts"]["category"] is None
    assert analysis["facts"]["month"] == "2026-09"


# L1: metadata that decodes to something other than an object is ignored.

@pytest.mark.parametrize("meta", ["null", "5", '"text"', "[]"])
def test_malformed_metadata_is_ignored(db, groceries, client, scripted, meta):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    db.add(models.ChatMessage(conversation_id=conversation_id, user_id=groceries.id,
                              role="assistant", content="old", meta=meta))
    db.commit()

    reply = _ask(client, conversation_id, "hello")

    assert reply["content"] == "ok"
    assert "THREAD CONTEXT: " not in model.last_system


def test_an_explicit_null_stops_older_context(db, groceries, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    db.add(models.ChatMessage(conversation_id=conversation_id, user_id=groceries.id,
                              role="assistant", content="a1",
                              meta=json.dumps({"analytics": context()})))
    db.add(models.ChatMessage(conversation_id=conversation_id, user_id=groceries.id,
                              role="assistant", content="a2",
                              meta=json.dumps({"analytics": None})))
    db.commit()

    _ask(client, conversation_id, "Why was April highest?")

    assert "THREAD CONTEXT: " not in model.last_system
    assert "VERIFIED ANALYTICS (intent:" not in model.last_system


# L2: a failed turn does not advance the thread's turn number.

def test_failed_turns_do_not_advance_the_context_turn(db, groceries, client, scripted, monkeypatch):
    import app.agent.providers as providers

    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much are we spending on groceries on average?")

    def boom(*args, **kwargs):
        raise providers.ProviderError("down")

    monkeypatch.setattr(providers, "ask", boom)
    for _ in range(2):
        response = client.post(f"/api/chat/conversations/{conversation_id}/messages",
                               json={"message": "Why was April highest?"})
        assert response.status_code == 503

    monkeypatch.setattr(providers, "ask", model)
    _ask(client, conversation_id, "Why was April highest?")

    rows = (db.query(models.ChatMessage)
            .filter(models.ChatMessage.conversation_id == conversation_id,
                    models.ChatMessage.role == "assistant")
            .order_by(models.ChatMessage.id).all())
    stored = json.loads(rows[-1].meta)["analytics"]
    assert stored["turn"] == 2, "two failed attempts must not skip turns"


# L3: an unknown category keeps the thread the user was on.

def test_an_unknown_category_keeps_the_previous_context(db, groceries):
    prior = context()
    analysis = planner.analyse(db, groceries, "How much did I spend on zzz in May?", today=TODAY,
                               context=prior, turn=2)

    assert analysis["intent"] == "unknown_category"
    assert analysis["context"]["category"] == "Groceries"
    assert analysis["context"]["month"] == "2026-04"

    corrected = planner.analyse(db, groceries, "No, I meant fuel", today=TODAY,
                                context=analysis["context"], turn=3)
    assert corrected["facts"]["categories"] == ["Fuel"]
    assert corrected["facts"]["month"] == "2026-04"


# ── F. category-aware merchant analytics (Task 27.3) ───────────────────────

@pytest.fixture()
def merchant_thread(db, user):
    """May: two grocery merchants, one restaurant, one fuel, one power bill."""
    rows = [
        ("Groceries", "BigBasket", 900, date(2026, 5, 3)),
        ("Groceries", "More Supermarket", 600, date(2026, 5, 9)),
        ("Restaurants", "Truffles", 1200, date(2026, 5, 12)),
        ("Fuel", "HP Petrol", 1500, date(2026, 5, 5)),
        ("Electricity", "BESCOM", 1200, date(2026, 5, 11)),
        ("Groceries", "BigBasket", 700, date(2026, 4, 20)),
    ]
    for category, description, amount, when in rows:
        db.add(models.Transaction(user_id=user.id, kind="expense", amount=Decimal(str(amount)),
                                  category=category, description=description,
                                  payment_method="UPI", txn_date=when))
    db.commit()
    return user


def test_the_merchant_thread_filters_by_the_thread_category(db, merchant_thread, client, scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)

    _ask(client, conversation_id, "Show my grocery spending in May.")
    assert "2026-05" in model.last_system

    facts = json.JSONDecoder().raw_decode(
        model.last_system.rsplit("FACTS: ", 1)[-1].lstrip())[0]
    # whatever turn 1 answered, the thread now carries Groceries + May
    assert facts.get("month") == "2026-05"

    _ask(client, conversation_id, "Which merchant contributed most?")
    facts = json.JSONDecoder().raw_decode(
        model.last_system.rsplit("FACTS: ", 1)[-1].lstrip())[0]
    assert facts["scope"] == "Groceries"
    assert facts["month"] == "2026-05"
    assert {m["merchant"] for m in facts["merchants"]} == {"BigBasket", "More Supermarket"}

    _ask(client, conversation_id, "No, I meant restaurants.")
    facts = json.JSONDecoder().raw_decode(
        model.last_system.rsplit("FACTS: ", 1)[-1].lstrip())[0]
    assert facts["scope"] == "Restaurants"
    assert facts["month"] == "2026-05"
    assert [m["merchant"] for m in facts["merchants"]] == ["Truffles"]

    _ask(client, conversation_id, "Which merchant contributed most overall?")
    facts = json.JSONDecoder().raw_decode(
        model.last_system.rsplit("FACTS: ", 1)[-1].lstrip())[0]
    assert facts["scope"] == "all categories"
    assert facts["month"] is None
    assert {m["merchant"] for m in facts["merchants"]} >= {"Truffles", "HP Petrol"}


def test_merchant_intent_uses_the_inherited_category(db, merchant_thread):
    prior = {"intent": "category_month", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 1, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "Which merchant contributed most?", today=TODAY,
                               context=prior, turn=2)

    assert analysis["intent"] == "merchants"
    assert analysis["facts"]["category"] == "Groceries"
    assert analysis["facts"]["month"] == "2026-05"
    assert analysis["facts"]["merchants"][0]["category"] == "Groceries"


def test_merchant_correction_replaces_the_category_and_keeps_the_month(db, merchant_thread):
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "No, I meant restaurants.", today=TODAY,
                               context=prior, turn=3)

    assert analysis["facts"]["category"] == "Restaurants"
    assert analysis["facts"]["scope"] == "Restaurants"
    assert analysis["facts"]["month"] == "2026-05"
    assert [m["merchant"] for m in analysis["facts"]["merchants"]] == ["Truffles"]


# ── G. unknown categories never widen the query (Task 27.3.1) ─────────────

def merchant_spy(monkeypatch):
    """Record what analytics.merchants() is called with."""
    from app.agent import analytics

    calls: list = []
    real = analytics.merchants

    def spy(*args, **kwargs):
        calls.append(kwargs.get("category"))
        return real(*args, **kwargs)

    monkeypatch.setattr(analytics, "merchants", spy)
    return calls


def test_an_unknown_category_correction_asks_and_never_queries(db, merchant_thread, monkeypatch):
    calls = merchant_spy(monkeypatch)
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "No, I meant boutiques.", today=TODAY,
                               context=prior, turn=3)

    assert analysis["intent"] == "unknown_category"
    facts = analysis["facts"]
    assert facts["status"] == "unknown_category"
    assert facts["category"] == "boutiques"
    assert facts["scope"] is None
    assert facts["month"] == "2026-05", "the period must survive an unknown category"
    assert "merchants" not in facts
    assert "Groceries" in facts["known_categories"]
    assert calls == [], "no merchant query may run for an unresolved category"


def test_an_unknown_category_switch_asks_instead_of_widening(db, merchant_thread, monkeypatch):
    calls = merchant_spy(monkeypatch)
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "and my school fees bill?", today=TODAY,
                               context=prior, turn=3)

    assert analysis["intent"] == "unknown_category"
    assert analysis["facts"]["month"] == "2026-05"
    assert calls == []


def test_a_recognised_correction_still_queries_the_new_category(db, merchant_thread, monkeypatch):
    calls = merchant_spy(monkeypatch)
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "No, I meant dining out.", today=TODAY,
                               context=prior, turn=3)

    assert analysis["facts"]["scope"] == "Dining Out"
    assert analysis["facts"]["month"] == "2026-05"
    assert calls == ["Dining Out"]


def test_a_bill_question_is_not_hijacked_by_the_merchant_thread(db, merchant_thread, monkeypatch):
    calls = merchant_spy(monkeypatch)
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread, "and my electricity bill?", today=TODAY,
                               context=prior, turn=3)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["categories"] == ["Electricity"]
    assert analysis["facts"]["month"] == "2026-05"
    assert calls == [], "a bill question is not a merchant question"


def test_an_explicit_merchant_question_still_uses_merchants(db, merchant_thread, monkeypatch):
    calls = merchant_spy(monkeypatch)
    prior = {"intent": "merchants", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 2, "updated_at": "x"}

    analysis = planner.analyse(db, merchant_thread,
                               "and which merchant contributed most for electricity?",
                               today=TODAY, context=prior, turn=3)

    assert analysis["intent"] == "merchants"
    assert analysis["facts"]["scope"] == "Electricity"
    assert analysis["facts"]["month"] == "2026-05"
    assert calls == ["Electricity"]


# ── H. category-vs-category comparison (Task 27.4) ────────────────────────

@pytest.fixture()
def comparison_thread(db):
    """A fresh ledger: May and June, two categories each."""
    user = models.User(name="CompareThread", email="compare-thread@local.dev", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    rows = [
        ("expense", "Groceries", "BigBasket", 900, date(2026, 5, 3)),
        ("expense", "Groceries", "More Supermarket", 600, date(2026, 5, 9)),
        ("expense", "Dining Out", "Truffles", 800, date(2026, 5, 12)),
        ("expense", "Fuel", "HP Petrol", 500, date(2026, 5, 5)),
        ("expense", "Groceries", "BigBasket", 700, date(2026, 6, 2)),
        ("expense", "Dining Out", "Truffles", 400, date(2026, 6, 7)),
        ("income", "Salary", "Employer", 90000, date(2026, 5, 1)),
        ("income", "Salary", "Employer", 88000, date(2026, 6, 1)),
    ]
    for kind, category, description, amount, when in rows:
        db.add(models.Transaction(user_id=user.id, kind=kind, amount=Decimal(str(amount)),
                                  category=category, description=description,
                                  payment_method="UPI", txn_date=when))
    db.commit()
    return user


def comparison_spy(monkeypatch):
    from app.agent import analytics

    calls: list = []
    real = analytics.compare_categories

    def spy(*args, **kwargs):
        calls.append((args[2] if len(args) > 2 else kwargs.get("first"),
                      args[3] if len(args) > 3 else kwargs.get("second"),
                      kwargs.get("month")))
        return real(*args, **kwargs)

    monkeypatch.setattr(analytics, "compare_categories", spy)
    return calls


def test_an_explicit_comparison_returns_both_totals(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "Compare Groceries vs Dining Out in May.", today=TODAY)

    assert analysis["intent"] == "compare_categories"
    facts = analysis["facts"]
    assert facts["month"] == "2026-05"
    assert [(c["category"], c["total"]) for c in facts["categories"]] == [
        ("Groceries", 1500.0), ("Dining Out", 800.0),
    ]
    assert facts["difference"] == 700.0
    assert facts["higher"] == "Groceries"


def test_a_which_is_higher_question_is_a_comparison(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "Which is higher, Fuel or Groceries in May?", today=TODAY)

    assert analysis["intent"] == "compare_categories"
    assert {c["category"] for c in analysis["facts"]["categories"]} == {"Fuel", "Groceries"}


def test_an_unknown_side_asks_and_never_queries(db, comparison_thread, monkeypatch):
    calls = comparison_spy(monkeypatch)

    analysis = planner.analyse(db, comparison_thread,
                               "Compare Groceries vs Yachts in May.", today=TODAY)

    assert analysis["intent"] == "unknown_category"
    assert analysis["facts"]["status"] == "unknown_category"
    assert analysis["facts"]["category"] == "Yachts"
    assert analysis["facts"]["month"] == "2026-05"
    assert calls == [], "an unknown side must not run the comparison query"


def test_ordinary_category_questions_stay_aggregates(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "How much did I spend on groceries in May?", today=TODAY)

    assert analysis["intent"] == "category_month"


def test_a_month_follow_up_keeps_the_comparison(db, comparison_thread):
    first = planner.analyse(db, comparison_thread,
                            "Compare Groceries vs Dining Out in May.", today=TODAY)
    follow = planner.analyse(db, comparison_thread, "What about June?", today=TODAY,
                             context=first["context"], turn=2)

    assert follow["intent"] == "compare_categories"
    assert [(c["category"], c["total"]) for c in follow["facts"]["categories"]] == [
        ("Groceries", 700.0), ("Dining Out", 400.0),
    ]
    assert follow["facts"]["month"] == "2026-06"


def test_which_one_was_higher_reuses_the_pair(db, comparison_thread):
    first = planner.analyse(db, comparison_thread,
                            "Compare Groceries vs Dining Out in May.", today=TODAY)
    follow = planner.analyse(db, comparison_thread, "Which one was higher?", today=TODAY,
                             context=first["context"], turn=2)

    assert follow["intent"] == "compare_categories"
    assert follow["facts"]["higher"] == "Groceries"
    assert follow["facts"]["month"] == "2026-05"


def test_an_ambiguous_comparison_asks_for_the_two_categories(db, comparison_thread, monkeypatch):
    calls = comparison_spy(monkeypatch)

    analysis = planner.analyse(db, comparison_thread, "Which category had higher spending?",
                               today=TODAY)

    assert analysis["intent"] == "clarify"
    assert "two categories" in analysis["facts"]["question"].lower()
    assert calls == []


def test_write_requests_are_not_routed_to_comparison(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "add a task to compare groceries and fuel", today=TODAY)

    assert analysis["intent"] != "compare_categories"


def test_a_comparison_remembers_filters_not_totals(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "Compare Groceries vs Dining Out in May.", today=TODAY)
    stored = analysis["context"]

    assert stored["comparison_target"] == "Dining Out"
    assert stored["category"] == "Groceries"
    assert set(stored) == {"intent", "category", "month", "kind", "comparison_target",
                           "turn", "updated_at"}
    assert "difference" not in stored and "categories" not in stored


def test_a_two_month_comparison_still_uses_the_month_comparator(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread, "Compare May and June", today=TODAY)

    assert analysis["intent"] == "compare_months"


# ── I. routing and follow-up hardening (Task 27.5.1) ──────────────────────

def analytics_spy(monkeypatch):
    """Record every analytics entry point the planner can reach."""
    from app.agent import analytics

    calls: list[str] = []
    names = ("search", "merchants", "compare_categories", "category_month", "category_series",
             "summary", "extremes", "highest_transactions", "monthly_series", "recurring")
    for name in names:
        real = getattr(analytics, name)

        def make(real=real, name=name):
            def spy(*args, **kwargs):
                calls.append(name)
                return real(*args, **kwargs)
            return spy

        monkeypatch.setattr(analytics, name, make())
    return calls


@pytest.mark.parametrize("message", [
    "Make it a task to pay rent on 20 November.",
    "Add a task to pay rent tomorrow.",
    "And delete the last one.",
])
def test_a_write_request_runs_no_analytics(db, comparison_thread, monkeypatch, message):
    calls = analytics_spy(monkeypatch)
    prior = {"intent": "compare_categories", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": "Dining Out", "turn": 1, "updated_at": "x"}

    analysis = planner.analyse(db, comparison_thread, message, today=TODAY, context=prior, turn=2)

    assert analysis["intent"] is None
    assert analysis["facts"] is None
    assert analysis["context"] == prior, "a write request must not rewrite the analytics thread"
    assert calls == [], f"analytics ran for a write request: {calls}"


def test_a_write_request_leaves_a_category_thread_untouched(db, comparison_thread, monkeypatch):
    calls = analytics_spy(monkeypatch)
    prior = {"intent": "list_transactions", "category": "Groceries", "month": "2026-05",
             "kind": "expense", "comparison_target": None, "turn": 3, "updated_at": "x"}

    analysis = planner.analyse(db, comparison_thread, "Add a task to pay rent on 20 November.",
                               today=TODAY, context=prior, turn=4)

    assert analysis["context"] == prior
    assert calls == []


def test_add_up_is_still_an_analytics_question(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread, "Add up my grocery spending in May.",
                               today=TODAY)

    assert analysis["intent"] == "category_month"
    assert analysis["facts"]["total"] == 1500.0


def test_a_mixed_request_keeps_its_analytics(db, comparison_thread):
    analysis = planner.analyse(db, comparison_thread,
                               "Show me my grocery spending and delete the last one.", today=TODAY)

    assert analysis["intent"] == "list_transactions"
    assert analysis["facts"]["category"] == "Groceries"


def test_a_write_turn_in_a_thread_runs_no_analytics(db, comparison_thread, client, scripted,
                                                    monkeypatch):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "How much did I spend on groceries in May?")

    before = (db.query(models.ChatMessage)
              .filter(models.ChatMessage.conversation_id == conversation_id,
                      models.ChatMessage.role == "assistant")
              .order_by(models.ChatMessage.id.desc()).first())
    before_meta = json.loads(before.meta)["analytics"]

    calls = analytics_spy(monkeypatch)
    model = scripted({"reply": "Added.", "actions": [{"op": "add_task", "text": "Pay rent",
                                                      "due": "2026-11-20"}]})
    reply = _ask(client, conversation_id, "Make it a task to pay rent on 20 November.")

    assert reply["applied"], "the write must still go through chat_focus/execution"
    assert "VERIFIED ANALYTICS (intent:" not in model.last_system
    after = (db.query(models.ChatMessage)
             .filter(models.ChatMessage.conversation_id == conversation_id,
                     models.ChatMessage.role == "assistant")
             .order_by(models.ChatMessage.id.desc()).first())
    assert json.loads(after.meta)["analytics"] == before_meta
    assert calls == []


# F2: an unfiltered listing is a new subject.

def test_an_unfiltered_listing_clears_the_comparison_context(db, comparison_thread):
    compare = planner.analyse(db, comparison_thread,
                              "Compare Groceries vs Dining Out in May.", today=TODAY)
    listing = planner.analyse(db, comparison_thread, "Show my transactions.", today=TODAY,
                              context=compare["context"], turn=2)

    assert listing["intent"] == "list_transactions"
    assert listing["facts"]["month"] is None and listing["facts"]["category"] is None
    assert listing["context"] is None, "an unfiltered listing must not keep the old comparison"

    follow = planner.analyse(db, comparison_thread, "Which one was higher?", today=TODAY,
                             context=listing["context"], turn=3)
    assert follow["intent"] == "clarify"
    assert "two categories" in follow["facts"]["question"].lower()


def test_a_filtered_listing_keeps_its_context(db, comparison_thread):
    listing = planner.analyse(db, comparison_thread,
                              "Show my grocery expenses in May.", today=TODAY)

    assert listing["context"]["category"] == "Groceries"
    assert listing["context"]["month"] == "2026-05"
    assert listing["context"]["intent"] == "list_transactions"


def test_an_unfiltered_listing_clears_the_context_end_to_end(db, comparison_thread, client,
                                                             scripted):
    model = scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)
    _ask(client, conversation_id, "Compare Groceries vs Dining Out in May.")
    _ask(client, conversation_id, "Show my transactions.")

    row = (db.query(models.ChatMessage)
           .filter(models.ChatMessage.conversation_id == conversation_id,
                   models.ChatMessage.role == "assistant")
           .order_by(models.ChatMessage.id.desc()).first())
    assert json.loads(row.meta)["analytics"] is None

    _ask(client, conversation_id, "Which one was higher?")
    assert "VERIFIED ANALYTICS (intent: compare_categories)" not in model.last_system


# F3: a month-only follow-up keeps the previous answer shape.

def test_month_follow_up_after_merchants_stays_merchants(db, comparison_thread):
    first = planner.analyse(db, comparison_thread, "Which merchants did I spend at?", today=TODAY)
    assert first["context"]["intent"] == "merchants"
    assert first["context"]["category"] is None and first["context"]["month"] is None

    follow = planner.analyse(db, comparison_thread, "What about June?", today=TODAY,
                             context=first["context"], turn=2)

    assert follow["intent"] == "merchants"
    assert follow["facts"]["month"] == "2026-06"
    assert follow["facts"]["scope"] == "all categories"


@pytest.mark.parametrize("message,month", [
    ("List my income transactions in May.", "2026-06"),
    ("Show my grocery expenses in May.", "2026-06"),
])
def test_month_follow_up_after_a_listing_stays_a_listing(db, comparison_thread, message, month):
    first = planner.analyse(db, comparison_thread, message, today=TODAY)
    assert first["intent"] == "list_transactions"

    follow = planner.analyse(db, comparison_thread, "What about June?", today=TODAY,
                             context=first["context"], turn=2)

    assert follow["intent"] == "list_transactions"
    assert follow["facts"]["month"] == month
    assert follow["facts"]["kind"] == first["facts"]["kind"]
    assert "transactions" in follow["facts"]


def test_a_month_follow_up_recomputes_rather_than_reusing_values(db, comparison_thread):
    first = planner.analyse(db, comparison_thread,
                            "Show my grocery expenses in May.", today=TODAY)
    db.add(models.Transaction(user_id=comparison_thread.id, kind="expense", amount=Decimal("250.00"),
                              category="Groceries", description="June top-up",
                              payment_method="UPI", txn_date=date(2026, 6, 20)))
    db.commit()

    follow = planner.analyse(db, comparison_thread, "What about June?", today=TODAY,
                             context=first["context"], turn=2)

    assert follow["facts"]["total"] == 950.0, "June must be re-queried after new rows exist"


def test_intent_only_merchant_context_survives_the_api(db, comparison_thread, client, scripted):
    scripted({"reply": "ok", "actions": []})
    conversation_id = _conversation(client)

    _ask(client, conversation_id, "Which merchants did I spend at?")
    row = (db.query(models.ChatMessage)
           .filter(models.ChatMessage.conversation_id == conversation_id,
                   models.ChatMessage.role == "assistant")
           .order_by(models.ChatMessage.id.desc()).first())
    stored = json.loads(row.meta)["analytics"]
    assert stored["intent"] == "merchants"
    assert stored["category"] is None and stored["month"] is None

    model = scripted({"reply": "ok", "actions": []})
    _ask(client, conversation_id, "What about June?")
    assert "VERIFIED ANALYTICS (intent: merchants)" in model.last_system
    assert '"month": "2026-06"' in model.last_system
