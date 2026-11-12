"""The conversation graph.

LangGraph runs each turn through four nodes:

    START → recall → think → (act?) → finish → END

* **recall**  – reads the user's records + durable memories and builds the prompt
* **think**   – asks the local model, falls back to the cloud model on failure
* **act**     – validates and executes the returned actions (deletes only propose)
* **finish**  – composes the reply and appends it to the thread's history

The checkpointer holds each conversation's message history in process, keyed by
`thread_id`, so a follow-up ("what about last month?") resolves against what was
said before. History is also persisted in Postgres by the API layer, which seeds
a fresh thread after a restart.

If `langgraph` cannot be imported (it is an optional dependency on odd
platforms), the same node functions run in sequence — identical output, no
checkpointing.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, TypedDict

from sqlalchemy.orm import Session

from .. import models
from ..ai import (
    DELETE_OPS,
    build_snapshot,
    clean_reply,
    execute_action,
    guard_action,
    parse_model_output,
    system_prompt,
)
from . import execution, focus as focus_mod, obs, planner, providers
from . import resolve as resolver
from .months import resolve_focus_month
from .reply import claims_change, normalize_currency

try:  # pragma: no cover - import guard
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except Exception:  # noqa: BLE001 - any import/loader failure degrades to sequential
    LANGGRAPH_AVAILABLE = False

HISTORY_LIMIT = 24
_SAVER = InMemorySaver() if LANGGRAPH_AVAILABLE else None

# A missing range must never be dressed up as a figure — the second net under
# the prompt rule.
_MONEY = re.compile(r"₹\s?[\d,]+(?:\.\d+)?")


class ChatState(TypedDict, total=False):
    message: str
    history: list[dict]
    snapshot: dict
    memories: list[str]
    system: str
    raw: str
    provider: str
    model: str
    degraded: str
    note: str
    reply: str
    actions: list[dict]
    results: list[dict]
    applied: list[dict]
    pending: list[dict]
    failed: list[dict]
    steps: list[str]
    retried: bool
    analytics: dict
    focus: dict
    data_range: dict
    conversation_id: str
    turn: int


def _json_ok(raw: str) -> None:
    """Raise ValueError when the model did not return a JSON object."""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"not a JSON object ({exc.__class__.__name__})") from exc
    if not isinstance(parsed, dict):
        raise ValueError("JSON was not an object")


def _memories(db: Session, user) -> list[str]:
    rows = (
        db.query(models.MemoryFact)
        .filter(models.MemoryFact.user_id == user.id)
        .order_by(models.MemoryFact.created_at.desc())
        .limit(40)
        .all()
    )
    return [row.fact for row in reversed(rows)]


def _facts_block(analysis: dict) -> str:
    """The verified analytics for this question, as the model sees them."""
    intent = analysis.get("intent")
    facts = analysis.get("facts")
    if not intent or not isinstance(facts, dict):
        return ""
    status = facts.get("status")
    header = f"VERIFIED ANALYTICS (intent: {intent})"
    if status and status != "ok":
        instruction = {
            "unknown_category": "That category does not exist in the user's data. Say so; never say zero.",
            "no_data": "There are no transactions in that range. Say the range is empty; never say zero.",
            "no_data_for_category": "That category has no spending in that range. Say exactly that.",
        }.get(status, "That range could not be read. Say so plainly; never invent a figure.")
        return (f"{header}\nSTATUS: {status}\n{instruction}\nFACTS: "
                f"{json.dumps(facts, default=str)[:2500]}")
    return (f"{header}\nThese numbers are computed from the database. Quote them exactly; "
            f"do not recompute or round differently.\nFACTS: {json.dumps(facts, default=str)[:4000]}")


def _nodes(db: Session, user, turn: int, prefer: str = "",
           conversation_id: str = "") -> dict[str, Callable[[ChatState], dict]]:
    def recall(state: ChatState) -> dict:
        history = list(state.get("history") or [])
        message = state.get("message") or ""
        if message:
            history = history + [{"role": "user", "content": message}]

        snapshot = build_snapshot(db, user, resolve_focus_month(message))
        memories = _memories(db, user)

        with obs.timed("plan"):
            analysis = planner.analyse(db, user, message)
        data_range = planner.available_range(db, user)
        current_focus = focus_mod.get(db, user, conversation_id) if conversation_id else None

        system = system_prompt(user, snapshot, memories, turn=turn)
        facts = _facts_block(analysis)
        if facts:
            system += "\n\n" + facts
        if current_focus:
            system += (
                "\n\nCURRENT FOCUS: this conversation is about "
                f"{current_focus['entity_type']} id={current_focus['entity_id']} "
                f"({current_focus['label']}). A follow-up that says 'it', 'that' or 'the "
                "same one' means this record. Ignore it when the new message names something else."
            )
        if data_range.get("status") == "ok":
            system += (f"\n\nDATA RANGE: transactions exist from {data_range['first_month']} to "
                       f"{data_range['last_month']} ({data_range['transactions']} rows). Anything "
                       "outside that range is missing data, never zero.")

        raw_facts = analysis.get("facts")
        obs.event("turn_start", conversation_id=conversation_id, turn=turn,
                  intent=analysis.get("intent"),
                  analytics_status=raw_facts.get("status") if isinstance(raw_facts, dict) else None,
                  focus=current_focus["entity_id"] if current_focus else None)


        raw_facts = analysis.get("facts")
        obs.event("turn_start", conversation_id=conversation_id, turn=turn,
                  intent=analysis.get("intent"),
                  analytics_status=raw_facts.get("status") if isinstance(raw_facts, dict) else None,
                  focus=current_focus["entity_id"] if current_focus else None)

        return {
            "history": history[-HISTORY_LIMIT:],
            "snapshot": snapshot,
            "memories": memories,
            "system": system,
            "analytics": analysis,
            "focus": current_focus or {},
            "data_range": data_range,
            "steps": ["recall"],
        }

    def think(state: ChatState) -> dict:
        prior = [
            {"role": m["role"], "content": m["content"]}
            for m in (state.get("history") or [])
            if m.get("role") in ("user", "assistant") and m.get("content")
        ][-10:]
        messages = [{"role": "system", "content": state.get("system", "")}, *prior]
        reply = providers.ask(messages, validate=_json_ok, prefer=prefer)
        text, actions = parse_model_output(reply.text)

        # A reply that says "Added both tasks." but carries no action is the one
        # failure the user cannot see coming — retry once, demanding the actions.
        if not actions and claims_change(text) and not state.get("retried"):
            retry_note = {
                "role": "system",
                "content": (
                    "Correction: your last reply claimed a change but returned no actions. "
                    "If the user asked you to add, change, complete or remove something, "
                    "return the actions now. If you cannot, reply that nothing was saved."
                ),
            }
            second = providers.ask([*messages, {"role": "assistant", "content": text}, retry_note],
                                   validate=_json_ok, prefer=prefer)
            second_text, second_actions = parse_model_output(second.text)
            if second_actions:
                reply, text, actions = second, second_text, second_actions

        return {
            "raw": reply.text,
            "provider": reply.provider,
            "model": reply.model,
            "degraded": reply.degraded,
            "note": reply.note,
            "reply": text,
            "actions": actions,
            "retried": True,
            "steps": (state.get("steps") or []) + ["think"],
        }

    def _other_type_hint(message: str, kind: str) -> str | None:
        """'Leave office at 7 PM is done' — that matched a journal entry, not a task."""
        for other in ("task", "journal", "note"):
            if other == kind:
                continue
            found = resolver.resolve(db, user, other, query=message)
            if not found.ok:
                continue
            label = resolver.describe(found.row, other)
            if other == "journal":
                return ('"' + label + '" is a journal entry, not a task — a journal entry records '
                        "what happened, so there is nothing to complete. Nothing was changed.")
            if other == "note":
                return ('"' + label + '" is a note, not a task — notes hold information, so there '
                        "is nothing to complete. Nothing was changed.")
            return f"That matches a {other} ({label}), not a {kind}. Nothing was changed."
        return None

    def act(state: ChatState) -> dict:
        results: list[dict] = []
        message = state.get("message") or ""

        for raw_action in (state.get("actions") or [])[:10]:
            action = focus_mod.apply(db, user, conversation_id, raw_action, message)
            op = str(action.get("op") or "")

            # An id inherited from the focus record is an explicit reference,
            # so the "does this row match the words?" check would only fight it.
            mismatch = None if action.get("from_focus") else guard_action(db, user, action, message)
            if mismatch:
                result = execution._result(op, op.split("_")[-1], success=False, error=mismatch)
                results.append(result)
                obs.inc("tool_failure")
                obs.event("tool_call", conversation_id=conversation_id, turn=turn, tool=op,
                          status="refused", error=mismatch[:120])
                continue

            if op in DELETE_OPS:
                probe = execution.execute(db, user, action, dry_run=True)
                if probe.get("success"):
                    probe["pending"] = True
                    results.append(probe)
                    obs.event("tool_call", conversation_id=conversation_id, turn=turn, tool=op,
                              status="pending", entity_id=probe.get("entity_id"))
                else:
                    results.append(probe)
                    obs.inc("tool_failure")
                    obs.event("tool_call", conversation_id=conversation_id, turn=turn, tool=op,
                              status="failed", error=(probe.get("error") or "")[:120])
                continue

            with obs.timed("execute"):
                result = execution.execute(db, user, action)
            obs.event("tool_call", conversation_id=conversation_id, turn=turn, tool=op,
                      entity_type=result.get("entity_type"), entity_id=result.get("entity_id"),
                      status="ok" if result.get("success") else "failed",
                      verified=result.get("verified"), error=(result.get("error") or "")[:160],
                      changes=result.get("changes") if result.get("success") else None)

            if not result.get("success") and "could not find" in (result.get("error") or "").lower():
                hint = _other_type_hint(message, str(result.get("entity_type") or ""))
                if hint:
                    result = {**result, "error": hint, "wrong_entity_type": True}

            if result.get("success"):
                focus_mod.set_focus(db, user, conversation_id,
                                    entity_type=result.get("entity_type", ""),
                                    entity_id=result.get("entity_id"),
                                    label=result.get("summary", ""), operation=op)
            results.append(result)

        applied = [r for r in results if r.get("success") and not r.get("pending")]
        pending = [r for r in results if r.get("pending")]
        failed = [r for r in results if not r.get("success")]
        return {
            "results": results,
            "applied": applied,
            "pending": pending,
            "failed": failed,
            "steps": (state.get("steps") or []) + ["act"],
        }

    def finish(state: ChatState) -> dict:
        applied = state.get("applied") or []
        pending = state.get("pending") or []
        failed = state.get("failed") or []
        reply = (state.get("reply") or "").strip()
        analysis = state.get("analytics") or {}
        facts = analysis.get("facts")

        if failed and not applied and not pending:
            # The execution layer's own words: "did not persist", "3 tasks match …"
            reply = failed[0].get("error") or "I could not do that — nothing was changed."
        elif not applied and not pending and not failed and claims_change(reply):
            obs.inc("false_success")
            obs.event("false_success_blocked", conversation_id=conversation_id, turn=turn,
                      reply=reply[:160])
            reply = ("Nothing was saved — I described that change but never recorded it, so your "
                     "data is unchanged. Say it again and I'll write it.")
        elif not reply:
            if applied:
                reply = "Done — " + "; ".join(a.get("summary", "") for a in applied) + "."
            elif pending:
                reply = "Confirm below and I'll remove it."
            else:
                reply = "I could not put that into words — try rephrasing with the amount and category."

        # A missing range must never surface as a rupee figure.
        if isinstance(facts, dict) and facts.get("status") in ("unknown_category", "no_data",
                                                              "no_data_for_category"):
            if _MONEY.search(reply):
                obs.inc("false_success")
                obs.event("zero_on_missing_data", conversation_id=conversation_id, turn=turn,
                          status=facts.get("status"), reply=reply[:160])
                reply = facts.get("message") or (
                    "I could not see any transactions for that range, so I cannot give a figure — "
                    "that is missing data, not zero.")
        reply = normalize_currency(clean_reply(reply, pending, applied))

        # Memories just written must be visible next turn, so re-read them.
        return {
            "reply": reply,
            "history": (state.get("history") or []) + [{"role": "assistant", "content": reply}],
            "steps": (state.get("steps") or []) + ["finish"],
        }

    return {"recall": recall, "think": think, "act": act, "finish": finish}


def _has_actions(state: ChatState) -> str:
    return "act" if state.get("actions") else "finish"


def _compile(nodes: dict[str, Callable]) -> Any:
    graph = StateGraph(ChatState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)
    graph.add_edge(START, "recall")
    graph.add_edge("recall", "think")
    graph.add_conditional_edges("think", _has_actions, {"act": "act", "finish": "finish"})
    graph.add_edge("act", "finish")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=_SAVER)


def thread_id(user, conversation_id: str) -> str:
    return f"u{user.id}:{conversation_id}"


def run_turn(
    db: Session,
    user,
    conversation_id: str,
    message: str,
    history: list[dict],
    turn: int,
    prefer: str = "",
) -> dict:
    """Run one turn of a conversation and return the reply plus what changed."""
    nodes = _nodes(db, user, turn, prefer, conversation_id=conversation_id)
    payload: ChatState = {
        "message": message,
        "history": history[-HISTORY_LIMIT:],
        "conversation_id": conversation_id,
        "turn": turn,
        # The checkpointer keeps a turn's channels until something overwrites
        # them, so an earlier turn's applied actions would otherwise be reported
        # as this turn's ("2 changes saved" for a question that changed nothing).
        "applied": [],
        "pending": [],
        "failed": [],
        "results": [],
        "actions": [],
        "reply": "",
        "raw": "",
        "degraded": "",
        "note": "",
        "retried": False,
    }

    if LANGGRAPH_AVAILABLE:
        try:
            graph = _compile(nodes)
            result = graph.invoke(payload, {"configurable": {"thread_id": thread_id(user, conversation_id)}})
            result["runner"] = "langgraph"
            return result
        except Exception as exc:  # noqa: BLE001 - never lose the turn to a graph error
            obs.event("graph_error", error=str(exc)[:200], conversation_id=conversation_id)
            state: dict = dict(payload)
            state["graph_error"] = str(exc)

    state = dict(payload)
    for name in ("recall", "think", "act", "finish"):
        if name == "act" and not state.get("actions"):
            continue
        update = nodes[name](state)  # type: ignore[arg-type]
        state.update(update or {})
    state["runner"] = "sequential"
    return state
