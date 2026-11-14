"""Short replies that approve the previous turn's proposal.

"Yes", "yes, do it", "go ahead", "proceed" are not requests on their own — they
approve something the assistant proposed a moment ago. Two rules keep that safe:

* the reply has to *be* a confirmation and nothing else — "yes, but make it 1200"
  is a new request and goes through the normal path;
* the record it lands on must be one this conversation was just working with
  (its focus record, or a record the previous turns created). A confirmation can
  never reach back to an older, unrelated record.
"""

from __future__ import annotations

import re


# Whole-message acknowledgements. Trailing politeness is allowed; new content is not.
_CONFIRM = re.compile(
    r"^\s*(?:"
    r"yes|yeah|yep|yup|ok|okay|alright|all right|sure|correct|exactly|right|agreed|"
    r"go ahead|proceed|do it|do that|please do it|please do that|please do|please go ahead|sounds good|"
    r"that'?s (?:correct|right|fine|it)|confirm(?:ed)?|approved?"
    r")(?:[\s,!.]*(?:please|now|then|go ahead|do it|do that|thanks|thank you))*[\s.!]*$",
    re.I,
)

# A refusal the turn can show when nothing is waiting for approval.
NOTHING_PENDING = ("There is nothing waiting for confirmation — tell me which record to "
                   "change and what to change on it.")
STALE_TARGET = ("That confirmation does not match what I proposed — nothing was changed. "
                "Say which record and what to change.")


def is_confirmation(message: str) -> bool:
    """True when the message does nothing but approve."""
    text = (message or "").strip()
    if not text or len(text) > 60:
        return False
    return bool(_CONFIRM.match(text))


def allowed_targets(kind: str, focus: dict | None, recent: dict[str, list[str]] | None) -> set[str]:
    """The ids this conversation was just working with, for one record kind."""
    targets: set[str] = set()
    if focus and str(focus.get("entity_type") or "") == kind:
        entity_id = focus.get("entity_id")
        if entity_id not in (None, ""):
            targets.add(str(entity_id))
    for entity_id in ((recent or {}).get(kind) or []):
        if entity_id not in (None, ""):
            targets.add(str(entity_id))
    return targets
