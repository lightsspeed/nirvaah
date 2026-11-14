"""Record resolution — the single place that decides *which* row a message means.

The old path matched with `needle in field`, which silently picks the first of
several matches and accepts near-misses. Everything here is deterministic:

    id → exact normalised title → token overlap (scored) → ambiguous / not found

A caller must never act on a row that came out of an ambiguous set, and must
never treat "no match" as "close enough".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from .. import models

# entity kind → (model, name field, human label)
ENTITIES: dict[str, tuple[type, str, str]] = {
    "task": (models.Task, "text", "task"),
    "note": (models.Note, "title", "note"),
    "journal": (models.JournalEntry, "title", "journal entry"),
    "goal": (models.Goal, "name", "goal"),
    "investment": (models.Investment, "name", "investment"),
    "liability": (models.Liability, "name", "liability"),
    "budget": (models.Budget, "category", "budget"),
    "transaction": (models.Transaction, "description", "transaction"),
}

# Words that describe the request rather than the record. "reschedule my servicing
# task" must score on "servicing", not on "task". The second block is instruction
# vocabulary: a follow-up often carries the whole sentence ("move the due date of
# the task 'Submit project report' from Friday to Monday, keep the title") and
# those words must not dilute the one name that identifies the row.
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "these", "those", "delete", "remove",
    "drop", "erase", "update", "change", "edit", "set", "make", "please", "can", "you", "your",
    "my", "our", "now", "under", "into", "out", "its", "it", "was", "were", "has", "have", "had",
    "transaction", "transactions", "expense", "expenses", "income", "record", "entry", "entries",
    "goal", "budget", "note", "notes", "task", "tasks", "journal", "investment", "liability",
    "one", "some", "all", "just", "about", "need", "want", "would", "like", "then", "than",
    "reschedule", "rename", "move", "mark", "complete", "completed", "done", "priority", "date",
    "due", "add", "create", "new", "high", "low", "medium", "next", "last", "today", "tomorrow",
    # instruction vocabulary
    "moved", "moving", "shift", "shifted", "postpone", "postponed", "push", "pushed", "keep",
    "keeping", "kept", "leave", "leaving", "title", "details", "detail", "rest", "everything",
    "unchanged", "other", "others", "same", "only", "should", "must", "still", "also", "after",
    "before", "instead", "rather", "wants", "prefer", "assume", "tell",
    # calendar words name a day, not a record
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "wed", "thu", "fri", "sat", "sun", "week", "weeks", "month", "months",
}

_WORD = re.compile(r"[a-z0-9]+")

# A match is only acted on once it clears this. Below it, the model's guess is
# treated as a guess.
ACCEPT_SCORE = 55


def normalise(value: object) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_tokens(value: object) -> list[str]:
    return [w for w in _WORD.findall(normalise(value)) if len(w) >= 3 and w not in STOPWORDS]


def _stem(word: str) -> str:
    return word[:5]


def record_text(row) -> str:
    """Every field that can identify a record, as one normalised string."""
    parts = []
    for name in ("description", "category", "name", "title", "text", "notes", "body",
                 "asset_type", "liability_type"):
        value = getattr(row, name, None)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    return normalise(" ".join(parts))


def score(row, query: str) -> int:
    """0–100. Exact beats prefix beats containment beats loose token overlap."""
    target = record_text(row)
    probe = normalise(query)
    if not probe or not target:
        return 0
    if target == probe:
        return 100
    name_field_values = [
        normalise(getattr(row, f, "")) for f in ("text", "title", "name", "category", "description")
        if isinstance(getattr(row, f, None), str)
    ]
    if probe in name_field_values:
        return 96
    if any(v.startswith(probe) or probe.startswith(v) for v in name_field_values if v):
        return 88
    if probe in target:
        return 76
    wanted = {_stem(t) for t in content_tokens(query)}
    if not wanted:
        return 0
    have = {_stem(w) for w in _WORD.findall(target) if len(w) >= 3}
    hit = wanted & have
    if not hit:
        return 0
    return int(30 + 50 * (len(hit) / len(wanted)))


@dataclass
class Candidate:
    row: object
    score: int
    label: str


@dataclass
class Resolution:
    status: str                      # matched | ambiguous | not_found | invalid_id
    row: object | None = None
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "matched" and self.row is not None


def describe(row, kind: str) -> str:
    """A short, human label for a record — no internal ids."""
    if kind == "task":
        extra = []
        if getattr(row, "due", None):
            extra.append(row.due.strftime("%d %b %Y"))
        if getattr(row, "done", False):
            extra.append("done")
        label = f'"{row.text}"'
        return label + (f" ({', '.join(extra)})" if extra else "")
    if kind == "note":
        return f'note "{row.title}"'
    if kind == "journal":
        when = row.event_date.strftime("%d %b %Y") if getattr(row, "event_date", None) else "no date"
        return f'journal entry "{row.title}" on {when}'
    if kind == "budget":
        return f"budget {row.category} for {row.month}"
    if kind in ("goal", "investment", "liability"):
        return f'{kind} "{row.name}"'
    if kind == "transaction":
        return (f"{row.txn_date.isoformat()} · {row.kind} · {row.category}"
                + (f" · {row.description}" if row.description else ""))
    return str(getattr(row, "id", "?"))


def _load(db: Session, model, raw_id):
    try:
        key = int(raw_id) if model in (
            models.Transaction, models.Budget, models.Goal, models.Investment, models.Liability
        ) else str(raw_id)
    except (TypeError, ValueError):
        return None
    return db.get(model, key)


def resolve(
    db: Session,
    user,
    kind: str,
    *,
    raw_id=None,
    query: str | None = None,
    limit: int = 4,
) -> Resolution:
    """Resolve one record for `kind`. Never returns a row from an ambiguous set."""
    spec = ENTITIES.get(kind)
    if not spec:
        return Resolution("not_found", message=f"{kind} records are not supported.")
    model, name_field, label = spec

    if raw_id not in (None, ""):
        row = _load(db, model, raw_id)
        if row is None or getattr(row, "user_id", None) != user.id:
            return Resolution("invalid_id", message=f"No {label} with that id belongs to you.")
        return Resolution("matched", row=row)

    if not query or not normalise(query):
        return Resolution("not_found", message=f"Which {label} do you mean?")

    rows = db.query(model).filter(model.user_id == user.id).all()
    scored = [Candidate(row=r, score=score(r, query), label=describe(r, kind)) for r in rows]
    scored = [c for c in scored if c.score > 0]
    scored.sort(key=lambda c: (-c.score, str(getattr(c.row, "id", ""))))

    if not scored:
        return Resolution("not_found", message=f"I could not find a {label} matching \"{query}\".")
    if scored[0].score < ACCEPT_SCORE:
        return Resolution("not_found",
                          message=f"I could not find a {label} matching \"{query}\" — nothing was changed.")

    top = scored[0].score
    ties = [c for c in scored if c.score == top]
    if len(ties) > 1:
        return Resolution(
            "ambiguous",
            candidates=ties[:limit],
            message=(
                f"{len(ties)} {label}s match \"{query}\": "
                + "; ".join(c.label for c in ties[:limit])
                + ". Which one did you mean?"
            ),
        )
    return Resolution("matched", row=scored[0].row, candidates=scored[:limit])
