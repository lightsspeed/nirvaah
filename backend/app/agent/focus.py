"""What "it" refers to.

Each conversation keeps one focus record in `chat_focus` (type, id, label, the
operation that put it there). A follow-up with a pronoun and no name of its own
inherits that id — nothing else does. A new message that names a record clears
or replaces the focus, so a change of topic cannot silently retarget an old one.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from .. import models
from . import obs

# "it", "that", "this", "them", "the same one", "its due date"…
PRONOUN = re.compile(
    r"\b(it|its|it's|that|this|them|they|those|these|same one|the same|the task|the note|"
    r"the record|the entry|the goal|the budget)\b",
    re.I,
)


def get(db: Session, user, conversation_id: str) -> dict | None:
    row = db.get(models.ChatFocus, conversation_id)
    if row is None or not row.entity_id:
        return None
    return {
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "label": row.label,
        "operation": row.operation,
        "updated_at": row.updated_at,
    }


def set_focus(db: Session, user, conversation_id: str, *, entity_type: str, entity_id, label: str,
              operation: str = "") -> None:
    if entity_id in (None, ""):
        return
    row = db.get(models.ChatFocus, conversation_id)
    if row is None:
        row = models.ChatFocus(conversation_id=conversation_id)
        db.add(row)
    row.entity_type = entity_type or ""
    row.entity_id = str(entity_id)
    row.label = (label or "")[:255]
    row.operation = (operation or "")[:40]
    row.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001 - focus is a convenience, never fail a turn
        db.rollback()
        obs.event("focus_write_failed", error=str(exc)[:160])


def clear(db: Session, conversation_id: str) -> None:
    row = db.get(models.ChatFocus, conversation_id)
    if row is not None:
        db.delete(row)
        try:
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()


def looks_like_followup(message: str) -> bool:
    return bool(PRONOUN.search(message or ""))


def apply(db: Session, user, conversation_id: str, action: dict, message: str) -> dict:
    """Give an action its referent when it has none of its own."""
    op = str(action.get("op") or "")
    if not op.startswith(("update_", "delete_")):
        return action
    if action.get("id") not in (None, ""):
        return action

    kind = op.split("_", 1)[1]
    name_field = {
        "task": "text", "note": "title", "journal": "title", "goal": "name",
        "investment": "name", "liability": "name", "budget": "category",
    }.get(kind)
    # The model already named the record — trust the name, not the focus.
    if name_field and str(action.get(name_field) or "").strip():
        return action
    if not looks_like_followup(message):
        return action

    focus = get(db, user, conversation_id)
    if not focus:
        return action
    if focus["entity_type"] != kind:
        # "make it high priority" while the focus is a note: give the model the
        # chance to have meant something else rather than retargeting silently.
        obs.event("focus_type_mismatch", focus_type=focus["entity_type"], action_type=kind)
        return action

    action = dict(action)
    action["id"] = focus["entity_id"]
    # An explicit reference: the word-overlap guard has nothing to add here.
    action["from_focus"] = True
    obs.event("focus_applied", entity_type=kind, entity_id=focus["entity_id"], operation=op)
    return action
