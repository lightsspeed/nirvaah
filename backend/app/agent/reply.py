"""Reply hygiene — keep internal ids out of the words the user sees.

Kept in its own module so the patterns are written as plain raw strings: an
escaped `\\b` that turns into a literal backspace byte compiles fine, matches
nothing, and silently disables the whole function.
"""

from __future__ import annotations

import re

# "id 757", "id#757", "with id 764"
_ID_MENTION = re.compile(r"\bid\s*#?\s*\d+\b", re.I)
# Everything from "with id 764" to the end of that clause.
_ID_CLAUSE = re.compile(r"\s*(?:with\s+)?id\s*#?\s*\d+", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def clean_reply(reply: str, pending: list | None = None, applied: list | None = None) -> str:
    """Drop sentences that leak an internal id; keep the answer readable."""
    text = (reply or "").strip()
    pending = pending or []
    applied = applied or []

    if not _ID_MENTION.search(text):
        return text

    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    kept = [s for s in sentences if not _ID_MENTION.search(s)]
    cleaned = " ".join(kept).strip()
    if cleaned:
        return cleaned
    if pending:
        return "I can remove that for you — confirm below."
    if applied:
        return "Done — " + "; ".join(a.get("summary", "") for a in applied) + "."
    return _ID_CLAUSE.sub("", text).strip() or text


_OTHER_CURRENCY = re.compile(r"[€$£]")


def normalize_currency(text: str, currency: str = "INR") -> str:
    """The ledger is INR; a stray euro/dollar glyph in an answer is a typo."""
    if currency != "INR":
        return text
    return _OTHER_CURRENCY.sub("₹", text or "")

# ── claims of a change that may not have happened ──────────────────────────
# A model that answers "Added both tasks." without emitting an action is the
# worst failure mode here: the user believes the write happened. These patterns
# spot a claim so the caller can retry once, and tell the truth if it still
# produced nothing.
_LEAD_CLAIM = re.compile(
    r"^\s*(done|added|created|updated|deleted|removed|saved|recorded|logged|marked|scheduled|renamed|noted|set)\b",
    re.I,
)
_IVE_CLAIM = re.compile(
    r"\bi'?ve (just )?(added|created|updated|saved|recorded|logged|deleted|removed|marked|noted|scheduled|renamed)\b",
    re.I,
)
_PENDING_CLAIM = re.compile(
    r"\b(adding|creating|updating|saving|recording|logging|deleting|removing|marking|scheduling|renaming)\b[^.!?]{0,40}\b(now|again)\b",
    re.I,
)
_NEGATED = re.compile(
    r"\b(didn'?t|did not|couldn'?t|could not|cannot|can'?t|unable|nothing|no changes?|not saved|failed)\b",
    re.I,
)


def claims_change(text: str) -> bool:
    """True when the reply asserts that something was written."""
    body = (text or "").strip()
    if not body or "?" in body:
        return False
    if _NEGATED.search(body):
        return False
    return bool(_LEAD_CLAIM.search(body) or _IVE_CLAIM.search(body) or _PENDING_CLAIM.search(body))
