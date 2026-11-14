"""Reply hygiene — keep internal ids out of the words the user sees.

Kept in its own module so the patterns are written as plain raw strings: an
escaped `\\b` that turns into a literal backspace byte compiles fine, matches
nothing, and silently disables the whole function.
"""

from __future__ import annotations

import json
import re

# "id 757", "id#757", "with id 764"
_ID_MENTION = re.compile(r"\bid\s*#?\s*\d+\b", re.I)
# Everything from "with id 764" to the end of that clause.
_ID_CLAUSE = re.compile(r"\s*(?:with\s+)?id\s*#?\s*\d+", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

# A model can put its whole structured answer inside the reply field: the tool
# payload then reaches the user as text ("Moving X to Wednesday.\n\n{"reply":…}").
# Task 30.4. Only blobs that carry the action contract are removed, so ordinary
# prose that happens to contain braces survives.
_PAYLOAD_KEYS = ('"reply"', '"actions"', '"op"', '"entity_id"', '"due"')
_REPLY_IN_BLOB = re.compile(r'"reply"\s*:\s*"(.*?)"\s*(?:,\s*"actions"|\}\s*$)', re.S)


def _blob_end(text: str, start: int) -> int:
    """Index of the brace that closes the one at `start`, or -1."""
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _strip_blobs(text: str) -> str:
    """Remove every `{…}` blob that looks like an action payload."""
    out: list[str] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            out.append(text[index:])
            break
        end = _blob_end(text, start)
        if end < 0:
            # Never closed: drop it when it is clearly the payload, keep it otherwise.
            if any(key in text[start:] for key in _PAYLOAD_KEYS):
                out.append(text[index:start])
            else:
                out.append(text[index:])
            break
        blob = text[start:end + 1]
        if not any(key in blob for key in _PAYLOAD_KEYS):
            out.append(text[index:start + 1])
            index = start + 1
            continue
        prose = text[index:start]
        out.append(prose)
        if not prose.strip():
            # Nothing else was said: keep whatever the blob says the answer was.
            salvaged = _REPLY_IN_BLOB.search(blob)
            if salvaged:
                out.append(salvaged.group(1).replace('\\"', '"').strip())
        index = end + 1
    return "".join(out)


def scrub_structured(text: str) -> str:
    """Strip structured output from a reply, keeping the words meant for the user.

    Handles the three shapes seen in practice: the whole reply is a JSON object,
    a JSON object is appended to the sentence, or the object is broken (so it
    cannot be parsed) and has to be cut out textually.
    """
    body = (text or "").strip()
    if not body:
        return ""
    if not any(key in body for key in _PAYLOAD_KEYS):
        return body

    # The whole reply may be the payload.
    if body.startswith("{"):
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            inner = str(parsed.get("reply") or "").strip()
            return scrub_structured(inner) if inner else ""

    cleaned = re.sub(r"[ \t]+\n", "\n", _strip_blobs(body))
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # Only the payload was there: let the caller word the turn from results.
    if cleaned.strip() in ("", "{}", "[]"):
        return ""
    return cleaned


def clean_reply(reply: str, pending: list | None = None, applied: list | None = None) -> str:
    """Drop structured output and sentences that leak an internal id."""
    text = scrub_structured((reply or "").strip())
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
    r"^\s*(done|added|created|updated|deleted|removed|saved|recorded|logged|marked|scheduled|"
    r"renamed|noted|set|moved|rescheduled|shifted|postponed|pushed|"
    r"changed|cleared|cancelled|canceled|checked off)\b",
    re.I,
)
_IVE_CLAIM = re.compile(
    r"\bi'?ve (just )?(added|created|updated|saved|recorded|logged|deleted|removed|marked|noted|"
    r"scheduled|renamed|moved|shifted|postponed|pushed|changed|rescheduled)\b",
    re.I,
)
# "Moving X to Wednesday" is a claim only when it moves something: a gerund on
# its own also opens ordinary sentences ("Moving averages smooth a noisy month").
_SOFT_CLAIM = re.compile(
    "^(moving|changing|rescheduling|shifting|postponing|pushing)(?![a-z])",
    re.I,
)
_OBJECT_CUE = re.compile(
    "[\"“”']|(?<![a-z])(tasks?|journals?|diary|notes?|budgets?|goals?|investments?|"
    "liabilit(?:y|ies)|transactions?|expenses?|income|records?|entries|entry|it|that)(?![a-z])|"
    "(?<![a-z])(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)(?![a-z])",
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
    if _SOFT_CLAIM.search(body):
        return bool(_OBJECT_CUE.search(body))
    return bool(_LEAD_CLAIM.search(body) or _IVE_CLAIM.search(body) or _PENDING_CLAIM.search(body))
