"""One message, several records.

The planner answers "is this a write?"; nothing answered "how many". A request
like *"Add ₹1,238 for Ramayan movie in Entertainment, also add as a journal
entry"* names two records, and a model that returns only one of them is not
obviously wrong — the turn simply ends with half the work done and a reply that
claims the whole.

This module closes that gap deterministically:

    requested_kinds(message)   what the user's own words ask to be created
    missing_kinds(...)         which of those the model's actions leave out
    partial_reply(...)         how to word a turn where only some were saved

Creation, not mention: "mark my gym task complete and add a journal note" names a
task and a journal entry, but only the journal entry is new. A kind counts when a
creation verb sits just before its noun, so an update never reads as a creation.
Transactions defer to `authority.authorize_creation`, which already understands a
reported spend and an amount stated without the noun "expense".
"""

from __future__ import annotations

import re

from .authority import LABELS, authorize_creation
from .resolve import normalise


# The kinds a personal-finance sentence realistically asks for in one breath.
# Notes are deliberately absent: "note in my journal" is a verb, and a bare
# "note" is too weak a signal to demand a second record.
KINDS = ("transaction", "journal", "task")

NOUNS: dict[str, re.Pattern] = {
    "journal": re.compile(r"\b(?:journals?|diary|diaries)\b"),
    "task": re.compile(r"\b(?:tasks?|to-?dos?|reminders?)\b"),
}

# What has to be said before the noun for the record to be *new* rather than
# mentioned: "add a journal entry", "note in my journal", "remind me to pay".
CREATE_VERBS: dict[str, re.Pattern] = {
    "journal": re.compile(r"\b(?:add|create|write|log|record|note|jot)\b"),
    "task": re.compile(r"\b(?:add|create|make|remind|schedule)\b"),
}

# How far back from the noun a creation verb still counts.
_WINDOW = 26


def _creation_phrase(text: str, kind: str) -> bool:
    """True when a creation verb sits just before this kind's noun."""
    for match in NOUNS[kind].finditer(text):
        start = max(0, match.start() - _WINDOW)
        if CREATE_VERBS[kind].search(text[start:match.start()]):
            return True
    return False


def requested_kinds(message: str) -> list[str]:
    """Record kinds this message asks to create, in a stable order."""
    text = normalise(message or "")
    if not text:
        return []
    kinds: list[str] = []
    for kind in KINDS:
        if kind == "transaction":
            # A reported spend, a record noun, or an amount tied to where the
            # money went — the same rule that authorises the write itself.
            if authorize_creation("add_transaction", message) is None:
                kinds.append(kind)
            continue
        if _creation_phrase(text, kind):
            kinds.append(kind)
    return kinds


def missing_kinds(message: str, actions: list[dict]) -> list[str]:
    """Requested kinds with no `add_*` action behind them.

    Empty unless the message asks for **two or more** records: a single-record
    request is already covered by the existing write-turn rules, and treating a
    one-record message as incomplete would turn ordinary requests into retries.
    """
    wanted = requested_kinds(message)
    if len(wanted) < 2:
        return []
    covered = {
        str(action.get("op") or "").split("_", 1)[-1]
        for action in (actions or [])
        if str(action.get("op") or "").startswith("add_")
    }
    return [kind for kind in wanted if kind not in covered]


def partial_reply(applied: list[dict], failed: list[dict]) -> str:
    """A reply built from verified results: what was saved, and what was not."""
    saved = "; ".join(r.get("summary") or "" for r in applied if r.get("summary"))
    misses: list[str] = []
    for result in failed:
        kind = str(result.get("entity_type") or "")
        label = LABELS.get(kind, kind or "record")
        reason = (result.get("error") or "it was not saved").strip().rstrip(".")
        misses.append(f"the {label}: {reason}")
    head = f"Done — {saved}." if saved else ""
    tail = "Not saved — " + "; ".join(misses) + "."
    return (head + " " + tail).strip()
