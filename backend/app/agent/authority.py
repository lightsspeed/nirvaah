"""Creation needs a request: the user's own words authorize every add_* action.

The model proposes an action; only the message can grant it. Before Task 27.6.1
every creation skipped `guard_action` entirely, so a model that answered a
question and also emitted ``add_transaction`` changed the ledger without being
asked (audit finding H1). This module answers one question, deterministically:

    did *this user message* ask for this kind of record to be created?

It is deliberately narrow. It reads the message, never the action's own text or
the model's explanation, and it fails closed: an unclear message means no write.
Amount, category and date validation stay where they were, in `execution`.
"""

from __future__ import annotations

import re

from .resolve import normalise


# What has to be named for each kind of record. The noun is what ties the action
# to the user's intent; a category name ("groceries") is not a record type.
NOUNS: dict[str, re.Pattern] = {
    "transaction": re.compile(
        r"\b(expenses?|transactions?|spends?|spending|payments?|income|salar(?:y|ies)|"
        r"earnings?|refunds?|credits?|debits?)\b"),
    "task": re.compile(r"\b(tasks?|to dos?|todos?|reminders?|remind)\b"),
    "note": re.compile(r"\b(notes?|jot)\b"),
    "journal": re.compile(r"\b(journal|diary|log)\b"),
    "goal": re.compile(r"\b(goals?|targets?)\b"),
    "budget": re.compile(r"\b(budgets?|limits?)\b"),
    "investment": re.compile(r"\b(investments?|invest|sips?|mutual funds?|stocks?)\b"),
    "liability": re.compile(r"\b(liabilit(?:y|ies)|loans?|debts?|emis?)\b"),
}

LABELS = {
    "transaction": "transaction", "task": "task", "note": "note",
    "journal": "journal entry", "goal": "goal", "budget": "budget",
    "investment": "investment", "liability": "liability",
}

# A verb that asks for something to be written down.
VERB = re.compile(
    r"\b(add|create|record|log|enter|save|note|jot|track|register|schedule|remind|make|set|"
    r"start|open|new)\b")

# "add up", "sum up", "break down" are arithmetic, not a request to create.
SUM_IDIOM = re.compile(r"\b(?:add|sum|count)\s+(?:it\s+|them\s+)?up\b|\bbreak\s+down\b")

# "I spent 500 on groceries", "paid 1200 for fuel" — in a bookkeeping assistant a
# first-person report of a money event *is* the request to record it. A bare verb
# is only trusted for the verbs that cannot open a question about money.
REPORT = re.compile(
    r"^\s*(?:please\s+|ok\s+|so\s+)?(?:"
    r"(?:i|we)\s+(?:spent|paid|bought|earned|received|got|made)\b"
    r"|(?:spent|paid|bought|earned|received)\b)")

# A message that opens as a question asks for an answer, not for a record.
QUESTION = re.compile(
    r"^\s*(?:what|which|where|when|why|who|how|do|does|did|is|are|was|were|has|have|had|"
    r"should|shall|will|would|could|can|may)\b")
# …unless the question is the polite frame around a request: "can you add …".
POLITE = re.compile(r"^\s*(?:please\s+|hey\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?")


def authorize_creation(op: str, message: str) -> str | None:
    """None when the message asks for this creation, else the refusal to show.

    ``op`` is the model's operation (``add_task``), ``message`` the user's words.
    """
    if not op.startswith("add_"):
        return None
    kind = op.split("_", 1)[1]
    nouns = NOUNS.get(kind)
    if nouns is None:
        return None          # unknown kind: execution rejects it by name

    text = normalise(message or "")
    if not text:
        return "Nothing was saved — there was no request to save anything."

    if SUM_IDIOM.search(text):
        return (f'Nothing was saved: "{message.strip()}" asks for a sum, not for a new '
                f"{LABELS[kind]}.")

    # "How can I save on expenses?" is a question even though it names a verb and
    # a record type; "can you add an expense?" is the same request with manners.
    head = text
    polite = POLITE.match(head)
    if polite:
        head = head[polite.end():]
    elif QUESTION.match(head):
        return _refusal(message, kind)

    if kind == "transaction":
        # A reported spend or receipt needs no other wording.
        if REPORT.search(text):
            return None
        if VERB.search(head) and nouns.search(head):
            return None
        return _refusal(message, kind)

    if VERB.search(head) and nouns.search(head):
        return None
    return _refusal(message, kind)


def _refusal(message: str, kind: str) -> str:
    label = LABELS.get(kind, kind)
    return (f'Nothing was saved: "{message.strip()}" does not ask me to add a {label}. '
            f"Tell me to add it if you want it recorded.")
