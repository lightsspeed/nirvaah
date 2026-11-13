"""HTTP surface for the assistant page: conversations, turns, memory."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..ai import DELETE_OPS
from ..timeutil import utcnow
from . import execution, focus as focus_mod, obs
from .credentials import credential_kind, refusal as credential_refusal
from ..database import get_db
from ..security import get_current_user
from ..timeutil import iso_utc
from ..tz import user_timezone, user_today
from . import graph, providers

router = APIRouter(prefix="/api/chat", tags=["assistant"])


def _conversation(db: Session, user, conversation_id: str) -> models.Conversation:
    row = db.get(models.Conversation, conversation_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return row


def _message_out(m: models.ChatMessage) -> dict:
    try:
        meta = json.loads(m.meta or "{}")
    except ValueError:
        meta = {}
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "provider": m.provider,
        "applied": meta.get("applied", []),
        "pending": meta.get("pending", []),
        "failed": meta.get("failed", []),
        "steps": meta.get("steps", []),
        "degraded": meta.get("degraded", ""),
        "note": meta.get("note", ""),
        # A turn can fail after a write committed; say so rather than implying a
        # clean turn (Task 27.6.2). The error is a classification, never a trace.
        "graph_error": meta.get("graph_error", ""),
        "partial": meta.get("partial", False),
        "uncertain": meta.get("uncertain", False),
        "at": iso_utc(m.created_at),
    }


def _conversation_out(c: models.Conversation, count: int = 0) -> dict:
    return {
        "id": c.id,
        "title": c.title,
        "provider": c.provider,
        "messages": count,
        "created_at": iso_utc(c.created_at),
        "updated_at": iso_utc(c.updated_at),
    }


class ConversationIn(BaseModel):
    title: str = ""


def _last_analytics_context(prior: list[models.ChatMessage]) -> dict | None:
    """The most recent turn's analytics filters, if this conversation had one.

    The newest assistant message wins even when it recorded "no context": that
    is how an explicit "overall" clears an old topic instead of resurrecting it.
    """
    for message in reversed(prior):
        if message.role != "assistant":
            continue
        try:
            meta = json.loads(message.meta or "{}")
        except ValueError:
            continue
        if not isinstance(meta, dict):
            # Valid JSON but not our metadata shape — ignore it, never fail a turn.
            continue
        if "analytics" in meta:
            context = meta["analytics"]
            return context if isinstance(context, dict) else None
    return None


class MessageIn(BaseModel):
    message: str
    # "", "local:<ollama model>" or "cloud:<model id>" from the model picker.
    prefer: str = ""


class ConfirmIn(BaseModel):
    actions: list[dict] = []


class MemoryIn(BaseModel):
    fact: str


_MEMORY_CUE = re.compile(r"\b(remember|from now on|going forward|keep in mind|note that i|don'?t forget)\b", re.I)
_MEMORY_STRIP = re.compile(
    r"^\s*(please\s+)?(remember|note|keep in mind)\s*(that\s+|to\s+)?|^\s*from now on,?\s*(please\s+)?",
    re.I,
)


def _memory_request(text: str) -> str | None:
    """A small model often forgets to emit {"op":"remember"}; the wording is a
    reliable enough signal to keep the fact ourselves."""
    if not _MEMORY_CUE.search(text or ""):
        return None
    fact = _MEMORY_STRIP.sub("", text).strip(" .")
    if len(fact) < 4:
        return None
    return fact[:400]


@router.get("/status")
def status(user=Depends(get_current_user)):
    return providers.status()


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.Conversation)
        .filter(models.Conversation.user_id == user.id)
        .order_by(models.Conversation.updated_at.desc())
        .all()
    )
    counts = {
        cid: n
        for cid, n in db.query(models.ChatMessage.conversation_id, func.count())
        .filter(models.ChatMessage.user_id == user.id)
        .group_by(models.ChatMessage.conversation_id)
        .all()
    }
    return [_conversation_out(c, counts.get(c.id, 0)) for c in rows]


@router.post("/conversations")
def create_conversation(data: ConversationIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = models.Conversation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=(data.title or "").strip()[:160] or "New conversation",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _conversation_out(row, 0)


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, data: ConversationIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = _conversation(db, user, conversation_id)
    if data.title.strip():
        row.title = data.title.strip()[:160]
        db.commit()
    return _conversation_out(row)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = _conversation(db, user, conversation_id)
    # chat_focus points at the conversation with no ON DELETE action, so the focus
    # row has to go in the same transaction; Postgres otherwise rejects the delete
    # and the conversation can never be removed. focus_mod.clear() commits on its
    # own, which would split the delete, so the rows are removed here directly.
    db.query(models.ChatFocus).filter(models.ChatFocus.conversation_id == row.id).delete()
    db.query(models.ChatMessage).filter(models.ChatMessage.conversation_id == row.id).delete()
    db.delete(row)
    db.commit()
    return {"deleted": True}


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _conversation(db, user, conversation_id)
    rows = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.conversation_id == conversation_id, models.ChatMessage.user_id == user.id)
        .order_by(models.ChatMessage.id.asc())
        .all()
    )
    return [_message_out(m) for m in rows]


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, data: MessageIn, db: Session = Depends(get_db),
                 user=Depends(get_current_user), today: date = Depends(user_today),
                 timezone_name: str | None = Depends(user_timezone)):
    conversation = _conversation(db, user, conversation_id)
    text = (data.message or "").strip()
    if not text:
        raise HTTPException(400, "Ask me something first.")

    prior = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.conversation_id == conversation_id, models.ChatMessage.user_id == user.id)
        .order_by(models.ChatMessage.id.asc())
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in prior if m.content]
    chat_context = _last_analytics_context(prior)
    # Count replies, not messages: a failed turn leaves a user message behind and
    # must not advance the thread's turn number (or its expiry clock).
    turn = sum(1 for m in prior if m.role == "assistant") + 1

    db.add(models.ChatMessage(
        conversation_id=conversation_id, user_id=user.id, role="user", content=text, meta="{}",
    ))
    db.commit()

    try:
        result = graph.run_turn(db, user, conversation_id, text, history, turn=turn,
                                prefer=(data.prefer or "").strip()[:80], today=today,
                                chat_context=chat_context)
    except providers.ProviderError as exc:
        raise HTTPException(503, str(exc)) from exc

    reply = result.get("reply") or ""
    applied = list(result.get("applied", []))
    pending = result.get("pending", [])
    failed = result.get("failed", [])

    # The model sometimes forgets the remember action. Only a message that asks
    # for a fact to be kept qualifies, and the write goes through the same
    # verified path as every other memory (Task 27.6.3).
    if not any(a.get("op") == "remember" for a in applied + pending + failed):
        from .authority import authorize_memory
        fact = _memory_request(text) if authorize_memory(text) is None else None
        if fact:
            remembered = execution.execute(db, user, {"op": "remember", "fact": fact},
                                           context={"today": today})
            if remembered.get("success"):
                applied.append(remembered)
                if not reply or "could not put that into words" in reply:
                    reply = "Noted — I'll remember that."
            else:
                failed.append(remembered)
                reply = remembered.get("error") or reply

    uncertain_result = any(r.get("uncertain") for r in applied + pending + failed)
    meta = {
        "applied": applied,
        "pending": pending,
        "failed": failed,
        "verified": all(a.get("verified") for a in applied) if applied else None,
        "steps": result.get("steps", []),
        "degraded": result.get("degraded", ""),
        "note": result.get("note", ""),
        "graph_error": result.get("graph_error", ""),
        "partial": bool(result.get("partial")),
        "uncertain": bool(result.get("uncertain")) or uncertain_result,
    }
    # Filters only: the next request inherits them and re-queries every figure.
    # A merchant or listing turn may carry only its intent, which is what a later
    # "what about June?" needs; an empty dict is an explicit reset.
    settled = result.get("chat_context")
    meta["analytics"] = settled if isinstance(settled, dict) and settled else None
    assistant = models.ChatMessage(
        conversation_id=conversation_id,
        user_id=user.id,
        role="assistant",
        content=reply,
        provider=result.get("provider", ""),
        meta=json.dumps(meta),
    )
    db.add(assistant)

    conversation.provider = result.get("provider", "")
    conversation.updated_at = utcnow()
    if conversation.title in ("", "New conversation"):
        first = text.split()
        conversation.title = " ".join(first[:7])[:160] + ("…" if len(first) > 7 else "")
    db.commit()
    db.refresh(assistant)

    obs.event("turn_end", conversation_id=conversation_id, turn=turn,
              applied=len(applied), pending=len(pending), failed=len(failed),
              verified=meta["verified"], runner=result.get("runner", ""),
              provider=result.get("provider", ""))

    out = _message_out(assistant)
    out["runner"] = result.get("runner", "")
    out["model"] = result.get("model", "")
    out["graph_error"] = result.get("graph_error", "")
    return out


@router.post("/conversations/{conversation_id}/confirm")
def confirm_deletes(conversation_id: str, data: ConfirmIn, db: Session = Depends(get_db),
                    user=Depends(get_current_user), today: date = Depends(user_today)):
    _conversation(db, user, conversation_id)
    context = {"today": today}
    applied, failed = [], []
    for action in (data.actions or [])[:10]:
        if action.get("op") not in DELETE_OPS:
            failed.append({"op": action.get("op"), "ok": False, "success": False, "verified": False,
                           "summary": "Only deletions need confirming."})
            continue
        result = execution.execute(db, user, action, context=context)
        obs.event("tool_call", conversation_id=conversation_id, tool=result.get("operation"),
                  entity_type=result.get("entity_type"), entity_id=result.get("entity_id"),
                  status="ok" if result.get("success") else "failed",
                  verified=result.get("verified"), confirmed=True,
                  error=(result.get("error") or "")[:160])
        if result.get("success"):
            applied.append(result)
            focus_mod.set_focus(db, user, conversation_id,
                                entity_type=result.get("entity_type", ""),
                                entity_id=result.get("entity_id"),
                                label=result.get("summary", ""), operation=result.get("operation", ""))
        else:
            failed.append({**result, "summary": result.get("error", "Could not delete that.")})
    return {"applied": applied, "failed": failed}


@router.get("/metrics")
def metrics(user=Depends(get_current_user)):
    """Reliability counters. A false success is an incident, so it leads."""
    return obs.metrics()


# ── durable memory ─────────────────────────────────────────────────────────

@router.get("/memories")
def list_memories(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(models.MemoryFact)
        .filter(models.MemoryFact.user_id == user.id)
        .order_by(models.MemoryFact.created_at.desc())
        .all()
    )
    return [
        {"id": r.id, "fact": r.fact, "at": iso_utc(r.created_at)}
        for r in rows
    ]


@router.post("/memories")
def add_memory(data: MemoryIn, db: Session = Depends(get_db), user=Depends(get_current_user)):
    fact = (data.fact or "").strip()
    if not fact:
        raise HTTPException(400, "Nothing to remember.")
    # Same guard as the assistant path: memories are replayed into prompts.
    kind = credential_kind(fact)
    if kind:
        obs.inc("memory_credential_refused")
        obs.event("memory_credential_refused", kind=kind)
        raise HTTPException(400, credential_refusal(kind))
    row = models.MemoryFact(user_id=user.id, fact=fact[:400], source="manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "fact": row.fact, "at": iso_utc(row.created_at)}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    row = db.get(models.MemoryFact, memory_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Memory not found")
    db.delete(row)
    db.commit()
    return {"deleted": True}
