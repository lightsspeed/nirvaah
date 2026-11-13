"""Verified mutations.

Every write goes: resolve → validate → capture before → commit → **read the row
back from the database** → compare. A reply can only call something "done" when
that read-back agrees.

The result shape is the contract the graph and the API speak:

    {
      "success": bool,
      "operation": "update_task",
      "entity_type": "task",
      "entity_id": "...",
      "changes": {"due": {"before": "2026-11-15", "after": "2026-11-21"}},
      "verified": bool,
      "uncertain": bool,     # the commit landed or not — we could not tell
      "error": None | str,
      # legacy keys the UI already renders
      "ok": bool, "op": "...", "summary": "...", "pending": bool
    }
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import DataError, IntegrityError, NotSupportedError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from .. import models
from decimal import Decimal

from ..money import ZERO, MoneyError, require_money, to_money
from ..timeutil import utcnow
from . import obs
from . import tasks as task_intel
from .credentials import credential_kind, refusal as credential_refusal
from . import resolve as resolver
from .fields import as_plain, date_value, inr, month, num, tags, text

WRITE_OPS = {"add", "update", "delete"}


@dataclass
class _Spec:
    model: type
    name_field: str | None
    label: str


# op suffix → model + the field a human would name it by
SPECS: dict[str, _Spec] = {
    "transaction": _Spec(models.Transaction, None, "transaction"),
    "budget": _Spec(models.Budget, "category", "budget"),
    "goal": _Spec(models.Goal, "name", "goal"),
    "investment": _Spec(models.Investment, "name", "investment"),
    "liability": _Spec(models.Liability, "name", "liability"),
    "note": _Spec(models.Note, "title", "note"),
    "task": _Spec(models.Task, "text", "task"),
    "journal": _Spec(models.JournalEntry, "title", "journal entry"),
}

STRING_PK = {models.Note, models.Task, models.JournalEntry}


# ── field builders ───────────────────────────────────────────────────────────

def _business_today(context: dict | None) -> date:
    """The caller's calendar date for defaults, or the server's day if none came in.

    ``context`` is built by the graph from ``timeutil.today_for_timezone`` — one
    resolved date for the whole turn, so a transaction and the journal entry it
    produces cannot land on different days.
    """
    value = (context or {}).get("today")
    return value if isinstance(value, date) else date.today()


def _transaction_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        kind = text(action, "kind", "expense").lower()
        if kind not in ("income", "expense"):
            raise ValueError("A transaction is either income or expense.")
        fields["kind"] = kind
        amount = to_money(num(action, "amount"))
        if amount <= ZERO:
            raise ValueError("A transaction needs an amount greater than zero.")
        fields["amount"] = amount
        fields["category"] = text(action, "category", "Other") or "Other"
        fields["description"] = text(action, "description")
        fields["payment_method"] = text(action, "payment_method", "SBI") or "SBI"
        fields["txn_date"] = date_value(action, "txn_date", _business_today(context))
        return fields
    if "kind" in action:
        kind = text(action, "kind").lower()
        if kind not in ("income", "expense"):
            raise ValueError("A transaction is either income or expense.")
        fields["kind"] = kind
    if "amount" in action:
        amount = to_money(num(action, "amount"))
        if amount <= ZERO:
            raise ValueError("A transaction needs an amount greater than zero.")
        fields["amount"] = amount
    for key in ("category", "description", "payment_method"):
        if key in action:
            fields[key] = text(action, key)
    if "txn_date" in action:
        fields["txn_date"] = date_value(action, "txn_date")
    return fields


def _budget_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        fields["category"] = text(action, "category") or "Other"
        fields["monthly_limit"] = require_money(num(action, "monthly_limit"),
                                                field="monthly_limit", positive=True)
        fields["month"] = month(action, today=_business_today(context))
        return fields
    if "monthly_limit" in action:
        fields["monthly_limit"] = require_money(num(action, "monthly_limit"),
                                                field="monthly_limit", positive=True)
    if "category" in action:
        fields["category"] = text(action, "category")
    if "month" in action:
        fields["month"] = month(action, today=_business_today(context))
    return fields


def _goal_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        fields["name"] = text(action, "name") or "Goal"
        fields["target_amount"] = require_money(num(action, "target_amount"),
                                                field="target_amount", positive=True)
        fields["saved_amount"] = require_money(num(action, "saved_amount", 0),
                                               field="saved_amount")
        fields["target_date"] = date_value(action, "target_date", None)
        return fields
    if "name" in action:
        fields["name"] = text(action, "name")
    for key, positive in (("target_amount", True), ("saved_amount", False)):
        if key in action:
            fields[key] = require_money(num(action, key), field=key, positive=positive)
    if "target_date" in action:
        fields["target_date"] = date_value(action, "target_date", None)
    return fields


def _investment_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        invested = require_money(num(action, "invested_amount", 0), field="invested_amount")
        fields["name"] = text(action, "name") or "Investment"
        fields["asset_type"] = text(action, "asset_type", "Mutual Fund") or "Mutual Fund"
        fields["invested_amount"] = invested
        fields["current_value"] = require_money(num(action, "current_value", invested),
                                                field="current_value")
        fields["notes"] = text(action, "notes")
        return fields
    for key in ("name", "asset_type", "notes"):
        if key in action:
            fields[key] = text(action, key)
    for key in ("invested_amount", "current_value"):
        if key in action:
            fields[key] = require_money(num(action, key), field=key)
    return fields


def _liability_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        fields["name"] = text(action, "name") or "Liability"
        fields["liability_type"] = text(action, "liability_type", "Loan") or "Loan"
        fields["outstanding_amount"] = require_money(num(action, "outstanding_amount", 0),
                                                     field="outstanding_amount")
        fields["monthly_emi"] = require_money(num(action, "monthly_emi", 0), field="monthly_emi")
        fields["notes"] = text(action, "notes")
        return fields
    for key in ("name", "liability_type", "notes"):
        if key in action:
            fields[key] = text(action, key)
    for key in ("outstanding_amount", "monthly_emi"):
        if key in action:
            fields[key] = require_money(num(action, key), field=key)
    return fields


def _note_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        fields["title"] = text(action, "title") or "Untitled note"
        fields["body"] = text(action, "body")
        fields["category"] = text(action, "category", "Personal") or "Personal"
        fields["tags"] = tags(action)
        return fields
    for key in ("title", "body", "category"):
        if key in action:
            value = text(action, key)
            if value or key != "title":  # a blank title is "no rename", not a wipe
                fields[key] = value
    if "tags" in action:
        fields["tags"] = tags(action)
    return fields


def _task_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        label = text(action, "text") or text(action, "title")
        if not label:
            raise ValueError("A task needs a title.")
        fields["text"] = label
        fields["notes"] = text(action, "notes")
        fields["priority"] = (text(action, "priority", "medium") or "medium").lower()
        fields["category"] = text(action, "category", "Personal") or "Personal"
        fields["due"] = date_value(action, "due", None)
        if "done" in action:
            fields["done"] = bool(action.get("done"))
        return fields
    if "text" in action:
        # An empty string is the model saying "no new title", not a request to
        # blank the task — only a real value renames it.
        value = text(action, "text")
        if value:
            fields["text"] = value
    if "notes" in action:
        fields["notes"] = text(action, "notes")
    if "done" in action:
        fields["done"] = bool(action.get("done"))
    if "priority" in action:
        fields["priority"] = (text(action, "priority") or "medium").lower()
    if "category" in action:
        fields["category"] = text(action, "category")
    if "due" in action:
        fields["due"] = date_value(action, "due", None)
    return fields


def _journal_fields(action: dict, *, creating: bool, context: dict | None = None) -> dict:
    fields: dict = {}
    if creating:
        fields["title"] = text(action, "title") or "Journal entry"
        fields["description"] = text(action, "description")
        fields["category"] = text(action, "category", "Life") or "Life"
        fields["mood"] = (text(action, "mood", "steady") or "steady").lower()
        # Nullable, but quantised and sign-checked like every other amount.
        fields["amount"] = (None if action.get("amount") in (None, "")
                            else require_money(num(action, "amount"), field="amount"))
        fields["event_date"] = date_value(action, "date", _business_today(context))
        fields["tags"] = tags(action)
        return fields
    for key in ("title", "description", "category", "mood"):
        if key in action:
            fields[key] = text(action, key)
    if action.get("amount") not in (None, ""):
        fields["amount"] = require_money(num(action, "amount"), field="amount")
    if "date" in action or "event_date" in action:
        fields["event_date"] = date_value(action, "date" if "date" in action else "event_date")
    if "tags" in action:
        fields["tags"] = tags(action)
    return fields


FIELD_BUILDERS = {
    "transaction": _transaction_fields,
    "budget": _budget_fields,
    "goal": _goal_fields,
    "investment": _investment_fields,
    "liability": _liability_fields,
    "note": _note_fields,
    "task": _task_fields,
    "journal": _journal_fields,
}


# ── result helpers ───────────────────────────────────────────────────────────

def _result(op: str, kind: str, *, success: bool, verified: bool = False,
            entity_id=None, changes: dict | None = None, error: str | None = None,
            summary: str = "", pending: bool = False, uncertain: bool = False) -> dict:
    return {
        "success": success,
        "verified": verified,
        # A write that may or may not have committed is neither success nor failure.
        "uncertain": uncertain,
        "operation": op,
        "op": op,
        "entity_type": kind,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "changes": changes or {},
        "error": error,
        # legacy shape the UI renders today
        "ok": success,
        "summary": summary,
        "id": entity_id,
        "pending": pending,
    }


def _same(left, right) -> bool:
    """Quantise both sides to paise, then compare — no tolerance to hide drift."""
    if isinstance(left, (float, Decimal, int)) and not isinstance(left, bool) \
            or isinstance(right, (float, Decimal, int)) and not isinstance(right, bool):
        try:
            return to_money(left) == to_money(right)
        except MoneyError:
            return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left.strip() == right.strip()
    return left == right


def _read_back(db: Session, model, pk):
    """A genuine database read: drop the identity map, then fetch."""
    db.expire_all()
    return db.get(model, pk)


# The database answered and rejected the transaction: the rollback is certain.
REJECTIONS = (IntegrityError, DataError, ProgrammingError, NotSupportedError)

UNCERTAIN = ("I could not confirm whether that change was saved — the connection dropped "
             "while it was being written. Please check the record before trying again.")


@dataclass(frozen=True)
class CommitOutcome:
    """The three states a commit can end in.

    ``ok``          committed and acknowledged.
    ``definite``    the database rejected it; nothing was saved.
    neither         the acknowledgement was lost; the row may exist.
    """

    ok: bool
    definite: bool = True
    error: str | None = None


def _safe_rollback(db: Session) -> None:
    """A dead connection cannot roll back; that must not mask the original error."""
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        obs.inc("rollback_failed")


def _probe_row(db: Session, model, pk):
    """Read the row over a fresh connection: (row, probe_ran).

    The session that lost the commit acknowledgement may be unusable, so the
    probe never reuses it. ``probe_ran`` is False when even the read failed —
    which proves nothing about the write.
    """
    try:
        probe = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)()
    except Exception as exc:  # noqa: BLE001
        obs.event("probe_failed", error=str(exc)[:160])
        return None, False
    try:
        return probe.get(model, pk), True
    except Exception as exc:  # noqa: BLE001 - the connection may still be gone
        obs.event("probe_failed", error=str(exc)[:160])
        return None, False
    finally:
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass


def _memory_persisted(db: Session, user, fact: str) -> bool:
    """Did this fact land? Same fresh-connection rule as _probe_row."""
    try:
        probe = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)()
    except Exception:  # noqa: BLE001
        return False
    try:
        return (probe.query(models.MemoryFact)
                .filter(models.MemoryFact.user_id == user.id, models.MemoryFact.fact == fact)
                .first() is not None)
    except Exception:  # noqa: BLE001
        return False
    finally:
        try:
            probe.close()
        except Exception:  # noqa: BLE001
            pass


def _commit(db: Session, op: str, kind: str) -> CommitOutcome:
    try:
        db.commit()
        return CommitOutcome(True)
    except REJECTIONS as exc:
        _safe_rollback(db)
        obs.inc("commit_failed")
        obs.event("commit_failed", operation=op, entity_type=kind, error=str(exc)[:200],
                  definite=True)
        return CommitOutcome(False, True,
                             "The database refused the change — nothing was saved.")
    except Exception as exc:  # noqa: BLE001 - connection loss: the outcome is unknown
        _safe_rollback(db)
        obs.inc("commit_uncertain")
        obs.event("commit_uncertain", operation=op, entity_type=kind, error=str(exc)[:200])
        return CommitOutcome(False, False, UNCERTAIN)


def _summarise(kind: str, verb: str, row) -> str:
    label = resolver.describe(row, kind)
    if kind == "task":
        return f"{verb} task {label}"
    if kind == "transaction":
        return f"{verb} transaction {label}"
    if kind == "budget":
        return f"{verb} budget {label}"
    return f"{verb} {kind} {label}"


# ── the executor ─────────────────────────────────────────────────────────────

def _remember(db: Session, user, action: dict, *, dry_run: bool, op: str) -> dict:
    """A memory fact, with the same commit-ambiguity rules as any other write."""
    label = text(action, "fact") or text(action, "text")
    if not label:
        return _result(op, "memory", success=False, error="Nothing to remember.")
    # A memory is replayed into every later prompt, so a credential must never
    # reach the database. The value is never echoed or logged (Task 27.6.3.2).
    kind = credential_kind(label)
    if kind:
        obs.inc("memory_credential_refused")
        obs.event("memory_credential_refused", kind=kind)
        return _result(op, "memory", success=False, error=credential_refusal(kind))
    if dry_run:
        db.rollback()
        # Nothing was written, so nothing can be verified.
        return _result(op, "memory", success=False,
                       error="Nothing was saved — that was a dry run.")
    db.add(models.MemoryFact(user_id=user.id, fact=label[:400],
                             source=text(action, "source")[:160]))
    outcome = _commit(db, op, "memory")
    if not outcome.ok and outcome.definite:
        return _result(op, "memory", success=False, error=outcome.error)
    if not outcome.ok and not _memory_persisted(db, user, label[:400]):
        obs.inc("commit_unconfirmed")
        return _result(op, "memory", success=False, uncertain=True, error=UNCERTAIN)
    return _result(op, "memory", success=True, verified=True,
                   summary=f"Remembered: {label[:140]}")


def execute(db: Session, user, action: dict, dry_run: bool = False, context: dict | None = None) -> dict:
    op = str(action.get("op") or "").strip()
    # The prompt documents {"op": "remember"} (rule 17); it names no entity kind,
    # so it is handled before the kind lookup rather than falling through it.
    if op == "remember":
        return _remember(db, user, action, dry_run=dry_run, op=op)
    if op.startswith("remember_"):
        return _remember(db, user, action, dry_run=dry_run, op=op)
    parts = op.split("_", 1)
    if len(parts) != 2:
        return _result(op, "unknown", success=False, error=f"I do not know how to {op or 'do that'}.")

    verb, kind = parts
    spec = SPECS.get(kind)
    if spec is None:
        return _result(op, kind, success=False, error=f"{kind} records are not something I can change.")

    if verb not in WRITE_OPS:
        return _result(op, kind, success=False, error=f"I do not know how to {op}.")

    builder = FIELD_BUILDERS[kind]

    # ── create ──────────────────────────────────────────────────────────────
    if verb == "add":
        try:
            fields = builder(action, creating=True, context=context)
        except ValueError as exc:
            return _result(op, kind, success=False, error=str(exc))
        pk = action.get("id") or (str(uuid.uuid4()) if spec.model in STRING_PK else None)
        row = spec.model(user_id=user.id)
        if pk is not None:
            row.id = pk
        for key, value in fields.items():
            setattr(row, key, value)
        if kind == "task":
            # A task created already done still gets one completion stamp.
            task_intel.set_done(row, bool(fields.get("done", False)), was=False)
        if hasattr(row, "updated_at"):
            row.updated_at = utcnow()
        db.add(row)
        outcome = _commit(db, op, kind)
        row_id = row.id

        if not outcome.ok and outcome.definite:
            return _result(op, kind, success=False, error=outcome.error)

        # Committed, or the acknowledgement was lost: the row itself decides. A
        # probe that cannot read proves nothing, so it yields "uncertain".
        if outcome.ok:
            fresh = _read_back(db, spec.model, row_id)
        else:
            fresh = _probe_row(db, spec.model, row_id)[0]
        if fresh is None:
            if not outcome.ok:
                obs.inc("commit_unconfirmed")
                return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                               error=UNCERTAIN)
            obs.inc("verify_failed")
            return _result(op, kind, success=False, entity_id=row_id,
                           error="The write did not persist — nothing was saved.")
        after = {k: as_plain(getattr(fresh, k, None)) for k in fields}
        mismatched = [k for k, v in fields.items() if not _same(after.get(k), as_plain(v))]
        if mismatched:
            if not outcome.ok:
                obs.inc("commit_unconfirmed")
                return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                               error=UNCERTAIN)
            obs.inc("verify_failed")
            obs.event("verify_failed", operation=op, entity_type=kind, entity_id=row_id,
                      fields=mismatched)
            return _result(op, kind, success=False, entity_id=row_id,
                           changes={k: {"before": None, "after": after.get(k)} for k in fields},
                           error=f"The change to {', '.join(mismatched)} did not persist.")
        obs.inc("tool_success")
        return _result(op, kind, success=True, verified=True, entity_id=row_id,
                       changes={k: {"before": None, "after": after.get(k)} for k in fields},
                       summary=_summarise(kind, "Added", fresh))

    # ── update / delete need a target ───────────────────────────────────────
    resolution = resolver.resolve(
        db, user, kind,
        raw_id=action.get("id"),
        query=text(action, spec.name_field) if spec.name_field else text(action, "description"),
    )
    if resolution.status == "ambiguous":
        obs.inc("ambiguous_target")
        obs.event("ambiguous_target", operation=op, entity_type=kind,
                  candidates=[c.label for c in resolution.candidates])
        return _result(op, kind, success=False, error=resolution.message)
    if not resolution.ok:
        obs.inc("tool_failure")
        obs.event("resolve_failed", operation=op, entity_type=kind,
                  query=text(action, spec.name_field) if spec.name_field else "", reason=resolution.status)
        return _result(op, kind, success=False,
                       error=resolution.message or f"I could not find that {spec.label}.")

    row = resolution.row
    row_id = row.id

    if verb == "delete":
        target = resolver.describe(row, kind)
        if dry_run:
            db.rollback()
            return _result(op, kind, success=True, verified=False, entity_id=row_id, pending=True,
                           summary=f"Delete {target}")
        if spec.model is models.Transaction:
            db.delete(row)
        else:
            db.add(models.Deletion(id=str(row_id), user_id=user.id, kind=kind))
            db.delete(row)
        outcome = _commit(db, op, kind)
        if not outcome.ok and outcome.definite:
            return _result(op, kind, success=False, entity_id=row_id, error=outcome.error)
        if outcome.ok:
            remaining = _read_back(db, spec.model, row_id)
        else:
            remaining, probe_ran = _probe_row(db, spec.model, row_id)
            if remaining is None and not probe_ran:
                obs.inc("commit_unconfirmed")
                return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                               error=UNCERTAIN)
        if remaining is not None:
            if not outcome.ok:
                obs.inc("commit_unconfirmed")
                return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                               error=UNCERTAIN)
            obs.inc("verify_failed")
            obs.event("verify_failed", operation=op, entity_type=kind, entity_id=row_id)
            return _result(op, kind, success=False, entity_id=row_id,
                           error=f"That {spec.label} is still in the database — nothing was removed.")
        obs.inc("tool_success")
        return _result(op, kind, success=True, verified=True, entity_id=row_id,
                       changes={"deleted": {"before": target, "after": None}},
                       summary=f"Deleted {target}")

    # ── update ──────────────────────────────────────────────────────────────
    try:
        fields = builder(action, creating=False, context=context)
    except ValueError as exc:
        return _result(op, kind, success=False, entity_id=row_id, error=str(exc))
    if not fields:
        return _result(op, kind, success=False, entity_id=row_id,
                       error=f"Nothing to change on that {spec.label}.")

    before = {key: as_plain(getattr(row, key, None)) for key in fields}
    was_done = bool(getattr(row, "done", False)) if kind == "task" else None
    for key, value in fields.items():
        setattr(row, key, value)
    if kind == "task" and "done" in fields:
        # One completion rule for every path: stamp on the transition to done,
        # keep the original stamp on a repeat, clear it on reopen.
        task_intel.set_done(row, bool(fields["done"]), was=was_done)
    if hasattr(row, "updated_at"):
        row.updated_at = utcnow()

    outcome = _commit(db, op, kind)
    intended = {k: {"before": before[k], "after": as_plain(v)} for k, v in fields.items()}
    if not outcome.ok and outcome.definite:
        return _result(op, kind, success=False, entity_id=row_id, changes=intended,
                       error=outcome.error)

    if outcome.ok:
        fresh = _read_back(db, spec.model, row_id)
    else:
        fresh = _probe_row(db, spec.model, row_id)[0]
    if fresh is None:
        if not outcome.ok:
            obs.inc("commit_unconfirmed")
            return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                           error=UNCERTAIN)
        obs.inc("verify_failed")
        return _result(op, kind, success=False, entity_id=row_id,
                       error=(f"That {spec.label} disappeared during the update — "
                              "the change did not persist, nothing was saved."))
    after = {key: as_plain(getattr(fresh, key, None)) for key in fields}
    mismatched = [k for k, v in fields.items() if not _same(after.get(k), as_plain(v))]
    changes = {k: {"before": before[k], "after": after.get(k)} for k in fields}
    if mismatched:
        if not outcome.ok:
            obs.inc("commit_unconfirmed")
            return _result(op, kind, success=False, entity_id=row_id, uncertain=True,
                           changes=changes, error=UNCERTAIN)
        obs.inc("verify_failed")
        obs.event("verify_failed", operation=op, entity_type=kind, entity_id=row_id,
                  fields=mismatched, changes=changes)
        return _result(op, kind, success=False, entity_id=row_id, changes=changes,
                       error=f"The {', '.join(mismatched)} change did not persist — nothing was saved.")

    obs.inc("tool_success")
    return _result(op, kind, success=True, verified=True, entity_id=row_id, changes=changes,
                   summary=_summarise(kind, "Updated", fresh))
