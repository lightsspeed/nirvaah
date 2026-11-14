"""What "it" refers to.

Each conversation keeps one focus record in `chat_focus` (type, id, label, the
operation that put it there). A follow-up with a pronoun and no name of its own
inherits that id — nothing else does. A new message that names a record clears
or replaces the focus, so a change of topic cannot silently retarget an old one.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models
from ..timeutil import utcnow
from . import obs
from . import resolve as resolver

# "it", "that", "this", "them", "the same one", "its due date"… and the
# relative forms the prompt already promises: "the last one", "the latest
# task", "the previous one", "the most recent one".
PRONOUN = re.compile(
    r"\b(it|its|it's|that|this|them|they|those|these|same one|the same|the task|the note|"
    r"the record|the entry|the goal|the budget|the last one|the latest one|the previous one|"
    r"the most recent one|"
    r"the (?:last|latest|previous|most recent) (?:task|note|record|entry|goal|budget|transaction|"
    r"investment|liability|reminder))\b",
    re.I,
)

# A name field that opens with one of these is the instruction, not the record:
# models routinely copy "Move the task to Monday" into `text`.
_INSTRUCTION_VERB = re.compile(
    r"^\s*(move|moved|change|changed|update|updated|reschedule|rescheduled|push|shift|postpone|"
    r"set|mark|rename|edit|keep|make)\b", re.I)
_DAY_WORD = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|"
    r"tomorrow|today|tonight|next week|this week)\b", re.I)


def _instruction_shaped(name: str) -> bool:
    """True when the 'name' reads as the sentence around the record."""
    return bool(_INSTRUCTION_VERB.search(name) or _DAY_WORD.search(name)) or len(name.split()) > 8


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
    row.updated_at = utcnow()
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


def apply(db: Session, user, conversation_id: str, action: dict, message: str,
          recent: dict[str, list[str]] | None = None) -> dict:
    """Give an action its referent when it has none of its own.

    ``recent`` maps an entity kind to the ids it was most recently *created* with
    in this conversation (the API reads it from the turns already stored). It is
    the fallback for the case the single focus row cannot cover: turn 1 creates a
    task and a journal entry, so focus points at the journal, and turn 2 says
    "move the task to Monday".
    """
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
    followup = looks_like_followup(message)

    # The model already named the record — trust the name, not the focus. A name
    # that matches nothing, though, is the instruction copied into the field:
    # "move the task to monday" resolves to no row, and only then does the
    # conversation decide.
    name = str(action.get(name_field) or "").strip() if name_field else ""
    if name:
        found = resolver.resolve(db, user, kind, query=name)
        if found.ok:
            if not _instruction_shaped(name):
                return action
            # The name carried the change too ("Submit project report from Friday
            # to Monday"): it found the row, so only the requested field is written.
            action = dict(action)
            action.pop(name_field, None)
            action["id"] = str(found.row.id)
            obs.event("focus_name_trimmed", entity_type=kind, entity_id=str(found.row.id))
            return action
        if not (followup or _instruction_shaped(name)):
            return action
        action = {k: v for k, v in action.items() if k != name_field}
        obs.event("focus_instruction_name", entity_type=kind, label=name[:60])

    if not followup:
        return action

    # The records this conversation most recently created of this kind decide
    # first: one means "the task", more than one means the user has to say which.
    batch = [str(i) for i in ((recent or {}).get(kind) or []) if i not in (None, "")]
    focused = get(db, user, conversation_id)
    if batch:
        candidates, source = batch, "recent"
    elif focused and focused["entity_type"] == kind:
        candidates, source = [str(focused["entity_id"])], "focus"
    else:
        candidates, source = [], ""

    if len(candidates) == 1:
        action = dict(action)
        action["id"] = candidates[0]
        # An explicit reference: the word-overlap guard has nothing to add here.
        action["from_focus"] = True
        obs.event("focus_applied", entity_type=kind, entity_id=candidates[0], operation=op,
                  source=source)
        return action
    if len(candidates) > 1:
        # More than one record could be "the task": ask, never guess.
        obs.event("focus_ambiguous", entity_type=kind, candidates=len(candidates))
    return action
