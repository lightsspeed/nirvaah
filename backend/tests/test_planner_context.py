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
    assert "VERIFIED ANALYTICS (intent: category_month)" in model.last_system
    assert '"month": "2026-05"' in model.last_system
    assert '"total": 900.0' in model.last_system

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
    assert resolved["reset"] is True


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
    """May: two grocery merchants, one restaurant, one fuel; April groceries."""
    rows = [
        ("Groceries", "BigBasket", 900, date(2026, 5, 3)),
        ("Groceries", "More Supermarket", 600, date(2026, 5, 9)),
        ("Restaurants", "Truffles", 1200, date(2026, 5, 12)),
        ("Fuel", "HP Petrol", 1500, date(2026, 5, 5)),
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
