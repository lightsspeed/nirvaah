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

# "Add ₹1,238 for Ramayan movie in Entertainment" names no record noun — the
# amount and where it went *are* the record. Without this, a compound request
# ("…, also add as a journal entry") authorised the journal and refused the
# expense, so the user was told both were saved while only one was.
# `normalise` strips the currency sign and the separators, so "₹1,238" is the
# two tokens "1 238": the amount check runs on the normalised text.
AMOUNT = re.compile(r"\b\d{2,}(?:\.\d{1,2})?\b")
SPEND_CUE = re.compile(r"\b(?:for|on|at|in|towards|toward)\b")
# A goal, budget or investment also carries an amount; those have their own noun
# and must not be recorded as spending.
OTHER_MONEY = re.compile(
    r"\b(?:goals?|targets?|budgets?|limits?|investments?|invest|sips?|mutual funds?|"
    r"stocks?|liabilit(?:y|ies)|loans?|debts?|emis?)\b")


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
        # A stated amount tied to where the money went ("₹1,238 for the Ramayan
        # movie in Entertainment") is a request to record a spend even when the
        # words "expense" or "transaction" never appear. The record noun is
        # implied, so demanding it refused real requests — including the expense
        # half of a compound one that also named a journal entry.
        if (VERB.search(head) and AMOUNT.search(text) and SPEND_CUE.search(text)
                and not OTHER_MONEY.search(text)):
            return None
        return _refusal(message, kind)

    if VERB.search(head) and nouns.search(head):
        return None
    return _refusal(message, kind)


def _refusal(message: str, kind: str) -> str:
    label = LABELS.get(kind, kind)
    return (f'Nothing was saved: "{message.strip()}" does not ask me to add a {label}. '
            f"Tell me to add it if you want it recorded.")


# ── memory ─────────────────────────────────────────────────────────────────
# A memory is a durable fact replayed into every later prompt, so storing one
# takes an instruction, not a mention. "Do you remember…" is a question about
# the assistant's memory: it may not create one (Task 27.6.3).
MEMORY_CUE = re.compile(
    r"\b(remember|keep in mind|bear in mind|note down|jot down|make a note|"
    r"don'?t forget|do not forget|from now on|going forward)\b", re.I)
# Recall, not instruction: addressed to the assistant, or asking what/when.
RECALL = re.compile(
    r"\b(?:do|did|can|could|would|will)\s+(?:you|i)\s+remember\b|"
    r"\bremember\s+(?:how|what|when|where|who|why|which|if|whether)\b|"
    r"\b(?:what|which|who)\s+should\s+(?:i|you)\s+remember\b", re.I)
# The instruction has to lead the message, or sit behind a polite frame.
LEADING_CUE = re.compile(
    r"^\s*(?:please\s+|ok\s+|okay\s+|and\s+|also\s+|so\s+)*"
    r"(?:i\s+(?:want|need|would like)\s+you\s+to\s+)?"
    r"(?:remember|keep in mind|bear in mind|note down|jot down|make a note|"
    r"don'?t forget|do not forget|from now on|going forward)\b", re.I)
POLITE_CUE = re.compile(
    r"^\s*(?:please\s+|hey\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"(?:remember|keep in mind|bear in mind|note down|jot down|make a note)\b", re.I)

NO_MEMORY_INTENT = ("Nothing was saved: that message does not ask me to remember "
                    "anything, so I did not store it.")


def authorize_memory(message: str) -> str | None:
    """None when the message asks for a fact to be kept, else the refusal to show.

    Reads the message only: the model's fact text is never evidence that the
    user asked for it to be remembered.
    """
    text = normalise(message or "")
    if not text:
        return NO_MEMORY_INTENT
    if RECALL.search(text):
        return NO_MEMORY_INTENT
    if not (LEADING_CUE.match(text) or POLITE_CUE.match(text)):
        return NO_MEMORY_INTENT
    if QUESTION.match(text) and not POLITE_CUE.match(text):
        return NO_MEMORY_INTENT
    return None
