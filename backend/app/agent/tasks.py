"""Deterministic due-date retrieval for tasks.

"What do I need to do today?" must not depend on the model reading a 30-row
snapshot and subtracting dates itself. These functions answer it from SQL: one
bounded page of rows, one grouped count, both filtered by the authenticated user
and by ``done``.

Everything here is read-only. There is no reminder delivery: a task with a due
date is a to-do, not a notification.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from .. import models
from ..timeutil import iso_utc, local_range_bounds, utcnow


WINDOWS = ("overdue", "today", "tomorrow", "upcoming", "week", "open", "date")
DEFAULT_HORIZON = 7
LIMIT = 20
MAX_LIMIT = 50
MAX_HORIZON = 60

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}
_WEEKDAY_RE = re.compile(r"\b(next\s+)?(" + "|".join(WEEKDAYS) + r")s?\b", re.I)
_NEXT_N_DAYS_RE = re.compile(r"\b(?:next|in\s+the\s+next|within\s+the\s+next|coming)\s+"
                             r"(\d{1,2})\s+days?\b", re.I)
# Expressions that name a date we cannot pin down. Guessing would put a wrong
# date in front of the user, so the planner asks instead.
_VAGUE_RE = re.compile(r"\b(?:in\s+a\s+few\s+days|sometime|soon|eventually|later\s+this\s+month|"
                       r"at\s+some\s+point)\b|\bon\s+the\s+\d{1,2}(?:st|nd|rd|th)\b", re.I)


# ── date resolution ─────────────────────────────────────────────────────────

def week_end(today: date) -> date:
    """Sunday of the current ISO week (Monday-first), inclusive."""
    return today + timedelta(days=6 - today.weekday())


def weekday_on_or_after(today: date, target: int, *, next_week: bool = False) -> date:
    """The documented weekday rule.

    A bare weekday is the soonest occurrence strictly after today (1–7 days
    ahead), so "Friday" asked on a Friday means the coming Friday, not today.
    "next <weekday>" is that weekday inside the *following* ISO week (8–14 days
    ahead), which keeps the two readings distinct instead of guessing.
    """
    if next_week:
        monday_next = today + timedelta(days=7 - today.weekday())
        return monday_next + timedelta(days=target)
    delta = (target - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def date_window(window: str, *, when: date | None = None, start: date | None = None,
                end: date | None = None, days: int | None = None) -> dict:
    """One shape for every resolved window. `date` keeps the day being asked about."""
    return {"ambiguous": False, "window": window, "days": days,
            "date": when.isoformat() if when else None,
            "start": (start or when).isoformat() if (start or when) else None,
            "end": (end or when).isoformat() if (end or when) else None}


def window_for(text: str, today: date) -> dict:
    """Which date window a message names — deterministic, no model involved."""
    lowered = text.lower()

    if _VAGUE_RE.search(lowered):
        return {"ambiguous": True,
                "question": ("Which day do you mean? I can check overdue, today, tomorrow, "
                             "this week, the next few days, or a weekday like Friday.")}

    for match in _WEEKDAY_RE.finditer(lowered):
        when = weekday_on_or_after(today, WEEKDAYS[match.group(2).lower()],
                                   next_week=bool(match.group(1)))
        return {**date_window("date", when=when), "rule": "weekday"}

    if re.search(r"\boverdue\b|\bpast\s+due\b|\brate\b", lowered):
        return date_window("overdue", end=today - timedelta(days=1))
    if re.search(r"\btomorrow\b", lowered):
        return date_window("tomorrow", when=today + timedelta(days=1))
    if re.search(r"\bthis\s+week\b|\brest\s+of\s+the\s+week\b", lowered):
        return date_window("week", start=today, end=week_end(today))
    horizon = _NEXT_N_DAYS_RE.search(lowered)
    if horizon:
        days = max(1, min(int(horizon.group(1)), MAX_HORIZON))
        return date_window("upcoming", start=today + timedelta(days=1),
                           end=today + timedelta(days=days), days=days)
    if re.search(r"\btoday\b", lowered):
        return date_window("today", when=today)
    if re.search(r"\bcoming\s+up\b|\bupcoming\b|\bnext\s+week\b", lowered):
        return date_window("upcoming", start=today + timedelta(days=1),
                           end=today + timedelta(days=DEFAULT_HORIZON),
                           days=DEFAULT_HORIZON)
    # No date named: "what's on my plate" is the whole open list.
    return date_window("open", end=today + timedelta(days=DEFAULT_HORIZON),
                       days=DEFAULT_HORIZON)


# ── retrieval ───────────────────────────────────────────────────────────────

def bucket_of(due: date | None, today: date) -> str:
    if due is None:
        return "undated"
    if due < today:
        return "overdue"
    if due == today:
        return "today"
    return "upcoming"


def _open(db: Session, user):
    """Only this user's tasks, and only the ones still to do."""
    return db.query(models.Task).filter(models.Task.user_id == user.id,
                                        models.Task.done.is_(False))


def _window(query, window: str, today: date, horizon: int, on: date | None):
    """Apply one window's SQL filter and return it with its period and order."""
    if window == "overdue":
        return (query.filter(models.Task.due.isnot(None), models.Task.due < today),
                {"start": None, "end": (today - timedelta(days=1)).isoformat()},
                (models.Task.due.asc(), models.Task.priority.desc()))
    if window == "today":
        return (query.filter(models.Task.due == today),
                {"start": today.isoformat(), "end": today.isoformat()},
                (models.Task.priority.desc(), models.Task.due.asc()))
    if window == "tomorrow":
        target = today + timedelta(days=1)
        return (query.filter(models.Task.due == target),
                {"start": target.isoformat(), "end": target.isoformat()},
                (models.Task.priority.desc(), models.Task.due.asc()))
    if window == "week":
        end = week_end(today)
        return (query.filter(models.Task.due >= today, models.Task.due <= end),
                {"start": today.isoformat(), "end": end.isoformat()},
                (models.Task.due.asc(), models.Task.priority.desc()))
    if window == "date":
        target = on or today
        return (query.filter(models.Task.due == target),
                {"start": target.isoformat(), "end": target.isoformat()},
                (models.Task.priority.desc(), models.Task.id.asc()))
    if window == "open":
        end = today + timedelta(days=horizon)
        return (query.filter(models.Task.due.isnot(None), models.Task.due <= end),
                {"start": None, "end": end.isoformat()},
                (models.Task.due.asc(), models.Task.priority.desc()))
    end = today + timedelta(days=horizon)                     # upcoming
    return (query.filter(models.Task.due > today, models.Task.due <= end),
            {"start": (today + timedelta(days=1)).isoformat(), "end": end.isoformat()},
            (models.Task.due.asc(), models.Task.priority.desc()))


def bucket_counts(db: Session, user, *, today: date, window: str = "open",
                  days: int | None = None, on: date | None = None) -> dict:
    """Exact overdue / today / upcoming counts for the window, grouped in SQL."""
    horizon = DEFAULT_HORIZON if days is None else max(1, min(int(days), MAX_HORIZON))
    query, _period, _order = _window(_open(db, user), window, today, horizon, on)
    bucket = case(
        (models.Task.due < today, "overdue"),
        (models.Task.due == today, "today"),
        else_="upcoming",
    ).label("bucket")
    rows = query.with_entities(bucket, func.count(models.Task.id)).group_by(bucket).all()
    counts = {"overdue": 0, "today": 0, "upcoming": 0}
    for name, number in rows:
        counts[name] = int(number or 0)
    return counts


# ── attention ───────────────────────────────────────────────────────────────

# "Open for a long time" is a measurable fact, not a verdict. Fourteen days is
# the threshold this assistant uses; the reason string always carries the number.
STALE_DAYS = 14
ATTENTION_LIMIT = 10
# The UI's own order (frontend/src/life/store.js: high 0, medium 1, low 2).
PRIORITY_ORDER = ("high", "medium", "low")

ATTENTION_RULES = (
    "overdue and high priority",
    "overdue",
    "high priority, due today or tomorrow",
    "due today or tomorrow",
    "high priority",
    f"open for at least {STALE_DAYS} days",
)


def priority_weight(priority: str | None) -> int:
    """The UI's own order; an unknown value sorts below low, never above high."""
    value = (priority or "").strip().lower()
    return PRIORITY_ORDER.index(value) if value in PRIORITY_ORDER else len(PRIORITY_ORDER)


def _rank_case(today: date):
    """One labelled CASE, reused for ORDER BY and read back as attention_rank."""
    high = func.lower(models.Task.priority) == "high"
    overdue = models.Task.due < today
    today_or_tomorrow = models.Task.due.in_([today, today + timedelta(days=1)])
    stale = func.date(models.Task.created_at) <= today - timedelta(days=STALE_DAYS)
    return case(
        (and_(overdue, high), 1),
        (overdue, 2),
        (and_(today_or_tomorrow, high), 3),
        (today_or_tomorrow, 4),
        (high, 5),
        (stale, 6),
        else_=7,
    )


def _attention_reasons(row, days_overdue, days_until, days_open) -> list[str]:
    """Why this task is here — each reason measurable from its own columns."""
    reasons: list[str] = []
    if days_overdue is not None:
        unit = "day" if days_overdue == 1 else "days"
        reasons.append(f"overdue by {days_overdue} {unit}")
    elif days_until == 0:
        reasons.append("due today")
    elif days_until == 1:
        reasons.append("due tomorrow")
    if (row.priority or "").strip().lower() == "high":
        reasons.append("high priority")
    if days_open is not None and days_open >= STALE_DAYS:
        reasons.append(f"open for {days_open} days")

    unique: list[str] = []
    for reason in reasons if reasons else ["no immediate date"]:
        if reason not in unique:
            unique.append(reason)
    return unique


def attention_tasks(db: Session, user, today: date | None = None,
                    limit: int = ATTENTION_LIMIT) -> dict:
    """Open tasks that deserve attention, ranked by why — not by guesswork.

    A task qualifies when it is overdue, due today or tomorrow, high priority, or
    has been open at least STALE_DAYS. The rank that orders the list is the same
    CASE that is returned with each row, so ordering and explanation cannot
    drift. Completed tasks never appear, and nothing is fetched outside user_id.
    """
    today = today or date.today()
    limit = ATTENTION_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    due_soon = today + timedelta(days=1)
    stale_before = today - timedelta(days=STALE_DAYS)

    qualifies = or_(
        models.Task.due <= due_soon,                       # overdue, today, tomorrow
        func.lower(models.Task.priority) == "high",
        func.date(models.Task.created_at) <= stale_before,
    )
    query = _open(db, user).filter(qualifies)
    count = query.with_entities(func.count(models.Task.id)).scalar() or 0

    rank = _rank_case(today)
    undated_last = case((models.Task.due.is_(None), 1), else_=0)
    weight = case(
        (func.lower(models.Task.priority) == "high", 0),
        (func.lower(models.Task.priority) == "medium", 1),
        (func.lower(models.Task.priority) == "low", 2),
        else_=3,
    )
    rows = (query.add_columns(rank.label("attention_rank"))
            .order_by(rank.asc(), undated_last.asc(), models.Task.due.asc(), weight.asc(),
                      models.Task.created_at.asc(), models.Task.id.asc())
            .limit(limit)
            .all())

    tasks = []
    for row, attention_rank in rows:
        days_overdue = (today - row.due).days if row.due and row.due < today else None
        days_until = (row.due - today).days if row.due and row.due >= today else None
        days_open = (today - row.created_at.date()).days if row.created_at else None
        tasks.append({
            "id": row.id,
            "text": row.text,
            "due": row.due.isoformat() if row.due else None,
            "priority": row.priority,
            "category": row.category,
            "days_overdue": days_overdue,
            "days_until": days_until,
            "days_open": days_open,
            "attention_rank": int(attention_rank),
            "attention_reasons": _attention_reasons(row, days_overdue, days_until, days_open),
        })

    facts = {
        "status": "ok" if count else "no_data",
        "today": today.isoformat(),
        "count": int(count),
        "shown": len(tasks),
        "truncated": len(tasks) < int(count),
        "limit": limit,
        "stale_days": STALE_DAYS,
        "priority_order": list(PRIORITY_ORDER),
        "rules": list(ATTENTION_RULES),
        "tasks": tasks,
    }
    if not count:
        facts["message"] = "No open tasks need attention right now."
    return facts


def due_tasks(db: Session, user, *, window: str = "today", today: date | None = None,
              days: int | None = None, on: date | None = None, limit: int = LIMIT) -> dict:
    """Task rows for one window, filtered and bounded in SQL.

    Windows:
        overdue   due before today
        today     due today
        tomorrow  due tomorrow
        week      today .. Sunday of this ISO week
        upcoming  tomorrow .. today + `days` (default 7)
        open      overdue, today and the horizon together, bucketed per row
        date      exactly one day (`on`, or the resolved weekday)

    Completed tasks are never returned. `count` is the database count; `tasks`
    is the bounded page, and `buckets` splits that count three ways.
    """
    today = today or date.today()
    window = window if window in WINDOWS else "today"
    limit = LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    horizon = DEFAULT_HORIZON if days is None else max(1, min(int(days), MAX_HORIZON))

    query, period, order = _window(_open(db, user), window, today, horizon, on)
    count = query.with_entities(func.count(models.Task.id)).scalar() or 0
    rows = query.order_by(*order).limit(limit).all()

    tasks = [{
        "id": row.id,
        "text": row.text,
        "due": row.due.isoformat() if row.due else None,
        "priority": row.priority,
        "category": row.category,
        "days_overdue": (today - row.due).days if row.due and row.due < today else None,
        "days_until": (row.due - today).days if row.due and row.due > today else None,
        "bucket": bucket_of(row.due, today),
    } for row in rows]

    facts = {
        "status": "ok" if count else "no_data",
        "window": window,
        "today": today.isoformat(),
        "start": period["start"],
        "end": period["end"],
        "count": int(count),
        "shown": len(tasks),
        "truncated": len(tasks) < int(count),
        "limit": limit,
        "buckets": bucket_counts(db, user, today=today, window=window, days=horizon, on=on),
        "tasks": tasks,
    }
    if not count:
        facts["message"] = f"No open tasks match {window}."
    return facts


# ── lifecycle ───────────────────────────────────────────────────────────────

def set_done(row, done: bool, *, was: bool | None = None,
             now: datetime | None = None) -> None:
    """The one completion rule, shared by the assistant and the REST path.

    Becoming complete stamps UTC once. Repeating "done" keeps the original
    stamp instead of re-dating the work. Reopening clears it, so completing
    again records a new stamp. A legacy row that is already complete with no
    stamp stays unstamped: its real date is unknowable, and inventing one would
    put a false date in front of the user.
    """
    previous = bool(getattr(row, "done", False)) if was is None else bool(was)
    done = bool(done)
    if done and not previous:
        row.completed_at = now or utcnow()
    elif not done:
        row.completed_at = None
    row.done = done


# ── completion history ──────────────────────────────────────────────────────

HISTORY_PERIODS = ("today", "yesterday", "week", "month", "last7", "last30", "recent")
# "last week" has no exact calendar meaning here; it is read as the last seven
# days, which is the only window the assistant can count without guessing.
_LAST7 = re.compile(r"\blast\s+7\s+days\b|\bpast\s+(?:7|seven)\s+days\b|\blast\s+week\b")
_LAST30 = re.compile(r"\blast\s+30\s+days\b|\bpast\s+(?:30|thirty)\s+days\b|\blast\s+month\b")
HISTORY_LIMIT = 20


def history_period(text: str, today: date) -> str | None:
    """Which completion period a message names, or None when it names none."""
    lowered = text.lower()
    if "yesterday" in lowered:
        return "yesterday"
    if _LAST7.search(lowered):
        return "last7"
    if _LAST30.search(lowered):
        return "last30"
    if re.search(r"\bthis\s+week\b", lowered):
        return "week"
    if re.search(r"\bthis\s+month\b", lowered):
        return "month"
    if re.search(r"\btoday\b", lowered):
        return "today"
    if re.search(r"\brecent(?:ly)?\b|\blatest\b|\bjust\b", lowered):
        return "recent"
    return None


def history_window(period: str, today: date) -> dict:
    """The local date range a completion period covers (`recent` has none)."""
    if period == "yesterday":
        day = today - timedelta(days=1)
        return {"period": "yesterday", "start": day.isoformat(), "end": day.isoformat()}
    if period == "week":
        monday = today - timedelta(days=today.weekday())
        return {"period": "week", "start": monday.isoformat(), "end": week_end(today).isoformat()}
    if period == "month":
        first = today.replace(day=1)
        last = first + timedelta(days=monthrange(today.year, today.month)[1] - 1)
        return {"period": "month", "start": first.isoformat(), "end": last.isoformat()}
    if period == "last7":
        return {"period": "last7", "start": (today - timedelta(days=6)).isoformat(),
                "end": today.isoformat()}
    if period == "last30":
        return {"period": "last30", "start": (today - timedelta(days=29)).isoformat(),
                "end": today.isoformat()}
    if period == "recent":
        return {"period": "recent", "start": None, "end": None}
    return {"period": "today", "start": today.isoformat(), "end": today.isoformat()}


def _period_bounds(window: dict, timezone_name: str | None):
    """UTC instants [start, end) for the window's local dates."""
    if not window["start"]:
        return None, None
    return local_range_bounds(date.fromisoformat(window["start"]),
                              date.fromisoformat(window["end"]), timezone_name)


def _task_row(row) -> dict:
    return {
        "id": row.id,
        "text": row.text,
        "due": row.due.isoformat() if row.due else None,
        "priority": row.priority,
        "category": row.category,
        "completed_at": iso_utc(row.completed_at),
    }


def completed_tasks(db: Session, user, *, period: str = "recent", today: date | None = None,
                    timezone_name: str | None = None, limit: int = HISTORY_LIMIT) -> dict:
    """Tasks completed in one period, ordered by completion time, bounded.

    Only rows with a `completed_at` can appear: a task finished before that
    column existed has no knowable completion date, so it is counted in
    `without_timestamp` and never presented as recent work.
    """
    today = today or date.today()
    window = history_window(period, today)
    limit = HISTORY_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    start_utc, end_utc = _period_bounds(window, timezone_name)

    query = db.query(models.Task).filter(models.Task.user_id == user.id,
                                         models.Task.done.is_(True),
                                         models.Task.completed_at.isnot(None))
    if start_utc is not None:
        query = query.filter(models.Task.completed_at >= start_utc,
                             models.Task.completed_at < end_utc)
    count = query.with_entities(func.count(models.Task.id)).scalar() or 0
    rows = (query.order_by(models.Task.completed_at.desc(), models.Task.id.desc())
            .limit(limit).all())

    undated = (db.query(func.count(models.Task.id))
               .filter(models.Task.user_id == user.id, models.Task.done.is_(True),
                       models.Task.completed_at.is_(None)).scalar() or 0)

    facts = {
        "status": "ok" if count else "no_data",
        "period": window["period"],
        "start": window["start"],
        "end": window["end"],
        "start_utc": iso_utc(start_utc),
        "end_utc": iso_utc(end_utc),
        "timezone": timezone_name or "UTC",
        "count": int(count),
        "shown": len(rows),
        "truncated": len(rows) < int(count),
        "limit": limit,
        "tasks": [_task_row(row) for row in rows],
        "without_timestamp": int(undated),
    }
    if not count:
        facts["message"] = (f"No completions are recorded for {window['period']}."
                            if window["start"] else "No tasks have a completion time yet.")
    return facts


def task_progress(db: Session, user, *, period: str = "month", today: date | None = None,
                  timezone_name: str | None = None) -> dict:
    """Completed-in-period next to the current open state, counting in SQL.

    `completed_count` is period-scoped; `pending_count`, `overdue_count` and
    `total_count` describe right now. They are different cohorts, so the facts
    also carry the all-time completion count and a `scope` note — there is no
    rate to compute from them.
    """
    today = today or date.today()
    window = history_window(period, today)
    start_utc, end_utc = _period_bounds(window, timezone_name)

    row = (db.query(
        func.sum(case((models.Task.done.is_(True), 1), else_=0)),
        func.sum(case((models.Task.done.is_(False), 1), else_=0)),
        func.sum(case((and_(models.Task.done.is_(False), models.Task.due.isnot(None),
                           models.Task.due < today), 1), else_=0)),
        func.sum(case((and_(models.Task.done.is_(True),
                            models.Task.completed_at.is_(None)), 1), else_=0)),
        func.count(models.Task.id),
    ).filter(models.Task.user_id == user.id).one())
    completed_all, pending, overdue, undated, total = [int(value or 0) for value in row]

    period_query = db.query(func.count(models.Task.id)).filter(
        models.Task.user_id == user.id, models.Task.done.is_(True),
        models.Task.completed_at.isnot(None))
    if start_utc is not None:
        period_query = period_query.filter(models.Task.completed_at >= start_utc,
                                           models.Task.completed_at < end_utc)
    completed_in_period = int(period_query.scalar() or 0)

    return {
        "status": "ok" if total else "no_data",
        "period": window["period"],
        "start": window["start"],
        "end": window["end"],
        "start_utc": iso_utc(start_utc),
        "end_utc": iso_utc(end_utc),
        "timezone": timezone_name or "UTC",
        "completed_count": completed_in_period,
        "pending_count": pending,
        "overdue_count": overdue,
        "total_count": total,
        "completed_all_time": completed_all,
        "without_timestamp": undated,
        "scope": {
            "completed_count": f"completed in {window['period']}",
            "pending_count": "currently incomplete",
            "overdue_count": "currently incomplete and past due",
            "total_count": "every task this user has opened, any status",
            "completed_all_time": "every task currently marked complete",
            "without_timestamp": "completed, but with no recorded completion date",
        },
        "message": ("No tasks recorded yet." if not total else
                    f"{completed_in_period} completed in {window['period']}, "
                    f"{pending} still pending ({overdue} overdue)."),
    }


# ── weekly review ───────────────────────────────────────────────────────────

WEEKLY_LIMIT = 10


def _later_tasks(db: Session, user, today: date, days: int, limit: int):
    """Open work that is not due in the near window and is not overdue.

    This is the tail of the pending list: the part that no other section shows,
    so the review never lists the same task twice.
    """
    horizon = today + timedelta(days=days)
    query = _open(db, user).filter(or_(models.Task.due.is_(None), models.Task.due > horizon))
    count = query.with_entities(func.count(models.Task.id)).scalar() or 0
    weight = case(
        (func.lower(models.Task.priority) == "high", 0),
        (func.lower(models.Task.priority) == "medium", 1),
        (func.lower(models.Task.priority) == "low", 2),
        else_=3,
    )
    undated_last = case((models.Task.due.is_(None), 1), else_=0)
    rows = (query.order_by(weight.asc(), undated_last.asc(), models.Task.due.asc(),
                           models.Task.created_at.asc(), models.Task.id.asc())
            .limit(limit).all())
    return int(count), [_task_row(row) for row in rows]


def weekly_review(db: Session, user, *, today: date | None = None,
                  timezone_name: str | None = None, limit: int = WEEKLY_LIMIT) -> dict:
    """One review of the current Monday–Sunday week, composed from the parts.

    Nothing is recalculated here: this week's completions come from
    completed_tasks, the counts from task_progress, overdue and upcoming from
    due_tasks, and attention from attention_tasks. The sections describe
    different scopes — this week's completions, everything still open, what is
    late, what is due soon — so no figure is subtracted from another and no rate
    is implied.
    """
    today = today or date.today()
    limit = WEEKLY_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    week_start = today - timedelta(days=today.weekday())
    week_finish = week_end(today)

    completed = completed_tasks(db, user, period="week", today=today,
                                timezone_name=timezone_name, limit=limit)
    progress = task_progress(db, user, period="week", today=today, timezone_name=timezone_name)
    overdue = due_tasks(db, user, window="overdue", today=today, limit=limit)
    upcoming = due_tasks(db, user, window="upcoming", days=DEFAULT_HORIZON, today=today,
                         limit=limit)
    attention = attention_tasks(db, user, today=today, limit=limit)
    later_count, later_rows = _later_tasks(db, user, today, DEFAULT_HORIZON, limit)

    # A task may legitimately appear in more than one section; say where, so the
    # reply can mention it once instead of three times.
    seen_in: dict[str, list[str]] = {}
    for section, rows in (("overdue", overdue["tasks"]), ("upcoming", upcoming["tasks"]),
                          ("pending", later_rows)):
        for row in rows:
            seen_in.setdefault(row["id"], []).append(section)

    attention_tasks_out = []
    for row in attention["tasks"]:
        entry = dict(row)
        elsewhere = [name for name in seen_in.get(row["id"], []) if name != "attention"]
        if elsewhere:
            entry["also_listed_in"] = elsewhere
        attention_tasks_out.append(entry)

    facts = {
        "status": "ok" if progress["total_count"] else "no_data",
        "week_start": week_start.isoformat(),
        "week_end": week_finish.isoformat(),
        "today": today.isoformat(),
        "timezone": timezone_name or "UTC",
        "limit": limit,
        "completed_count": progress["completed_count"],
        "pending_count": progress["pending_count"],
        "overdue_count": progress["overdue_count"],
        "attention_count": attention["count"],
        "upcoming_count": upcoming["count"],
        "without_timestamp": progress["without_timestamp"],
        "sections": {
            "completed": {
                "scope": f"completed between {week_start.isoformat()} and "
                         f"{week_finish.isoformat()}",
                "count": completed["count"],
                "shown": completed["shown"],
                "truncated": completed["truncated"],
                "tasks": completed["tasks"],
            },
            "pending": {
                "scope": "open tasks not overdue and not due in the next seven days",
                "count": later_count,
                "shown": len(later_rows),
                "truncated": len(later_rows) < later_count,
                "tasks": later_rows,
            },
            "overdue": {
                "scope": "open tasks whose due date has passed",
                "count": overdue["count"],
                "shown": overdue["shown"],
                "truncated": overdue["truncated"],
                "tasks": overdue["tasks"],
            },
            "attention": {
                "scope": "open tasks ranked by why they need attention",
                "count": attention["count"],
                "shown": len(attention_tasks_out),
                "truncated": len(attention_tasks_out) < attention["count"],
                "tasks": attention_tasks_out,
            },
            "upcoming": {
                "scope": f"open tasks due {upcoming['start']} to {upcoming['end']}",
                "start": upcoming["start"],
                "end": upcoming["end"],
                "count": upcoming["count"],
                "shown": upcoming["shown"],
                "truncated": upcoming["truncated"],
                "tasks": upcoming["tasks"],
            },
        },
        "scope": {
            "completed_count": "completed this week (Monday to Sunday, local dates)",
            "pending_count": "every task still open, any due date",
            "overdue_count": "open tasks past their due date",
            "attention_count": "open tasks with at least one attention reason",
            "upcoming_count": "open tasks due in the next seven days",
            "pending_section": "only the open tasks no other section lists",
        },
    }
    if not progress["total_count"]:
        facts["message"] = "No tasks recorded yet."
    return facts


# ── insights ────────────────────────────────────────────────────────────────

INSIGHT_LIMIT = 10
INSIGHT_SEVERITY = {"critical": 0, "warning": 1, "info": 2}
# Within one severity, the order the user should read them in.
INSIGHT_ORDER = {"high_priority_overdue": 0, "overdue_cluster": 1, "due_soon": 2, "long_open": 3}
# Three of a kind is a pattern worth naming; one or two is ordinary work.
RULE_B_OVERDUE = 3
RULE_C_DUE_SOON = 3
RULE_D_LONG_OPEN = 3


def _long_open(db: Session, user, today: date, limit: int):
    """Open tasks older than the staleness threshold: (count, rows)."""
    cutoff = today - timedelta(days=STALE_DAYS)
    query = _open(db, user).filter(func.date(models.Task.created_at) <= cutoff)
    count = query.with_entities(func.count(models.Task.id)).scalar() or 0
    rows = (query.order_by(models.Task.created_at.asc(), models.Task.id.asc())
            .limit(limit).all())
    return int(count), rows


def _count_open(db: Session, user, *conditions) -> int:
    query = _open(db, user).filter(*conditions)
    return int(query.with_entities(func.count(models.Task.id)).scalar() or 0)


def generate_task_insights(db: Session, user, *, today: date | None = None,
                           timezone_name: str | None = None,
                           limit: int = INSIGHT_LIMIT) -> dict:
    """Deterministic, evidence-backed observations about the task list.

    Every figure comes from due_tasks / the long-open query and every insight
    names the tasks behind it. The rules describe a situation; none of them
    decides anything, recommends a change it has already made, or invents a
    consequence. When nothing qualifies the result is an explicit empty list —
    there is no generic filler insight.
    """
    today = today or date.today()
    limit = INSIGHT_LIMIT if limit is None else max(1, min(int(limit), MAX_LIMIT))
    evaluated_at = iso_utc(utcnow())

    # Evaluate against the largest page the module allows, then cut the answer
    # to  — otherwise a small limit would silently shrink every count.
    page = MAX_LIMIT
    overdue = due_tasks(db, user, window="overdue", today=today, limit=page)
    due_today = due_tasks(db, user, window="today", today=today, limit=page)
    due_tomorrow = due_tasks(db, user, window="tomorrow", today=today, limit=page)
    long_open_count, long_open_rows = _long_open(db, user, today, page)

    insights: list[dict] = []

    def insight(key: str, kind: str, severity: str, title: str, message: str,
                evidence: dict, task_ids: list[str], action: str) -> dict:
        return {
            "id": key,
            "dedupe_key": key,
            "type": kind,
            "severity": severity,
            "title": title,
            "message": message,
            "evidence": evidence,
            "task_ids": task_ids,
            "recommended_action": action,
            "evaluated_at": evaluated_at,
        }

    # ── Rule A: a high-priority task is already late ──────────────────────
    high_overdue_total = _count_open(db, user, models.Task.due.isnot(None),
                                     models.Task.due < today,
                                     func.lower(models.Task.priority) == "high")
    high_overdue_rows = [task for task in overdue["tasks"]
                         if (task["priority"] or "").lower() == "high"]
    for task in high_overdue_rows[:MAX_LIMIT]:
        days = task["days_overdue"]
        insights.append(insight(
            f"task_overdue_high:{task['id']}", "high_priority_overdue", "critical",
            "High-priority task is overdue",
            f"\"{task['text']}\" is overdue by {days} {'day' if days == 1 else 'days'} "
            f"and is marked high priority.",
            {"task_id": task["id"], "text": task["text"], "due": task["due"],
             "days_overdue": days, "priority": task["priority"],
             "high_priority_overdue_total": high_overdue_total},
            [task["id"]],
            "Decide today whether to finish it, move the due date, or drop it.",
        ))

    # ── Rule B: several tasks are past due (the cluster, not the same list) ─
    if overdue["count"] >= RULE_B_OVERDUE:
        oldest_days = max((task["days_overdue"] or 0) for task in overdue["tasks"]) \
            if overdue["tasks"] else 0
        insights.append(insight(
            "overdue_cluster", "overdue_cluster", "warning",
            "Several tasks are overdue",
            f"{overdue['count']} open tasks are past due, {high_overdue_total} of them high "
            f"priority; the oldest is {oldest_days} days late.",
            {"overdue_count": overdue["count"],
             "high_priority_overdue": high_overdue_total,
             "oldest_days_overdue": oldest_days,
             "task_ids": [task["id"] for task in overdue["tasks"]]},
            [task["id"] for task in overdue["tasks"]],
            "Review the overdue list and reschedule what is no longer realistic.",
        ))

    # ── Rule C: a cluster of deadlines inside 48 hours ────────────────────
    due_soon_count = due_today["count"] + due_tomorrow["count"]
    if due_soon_count >= RULE_C_DUE_SOON:
        soon_rows = due_today["tasks"] + due_tomorrow["tasks"]
        insights.append(insight(
            "due_soon_48h", "due_soon", "warning",
            "Deadlines within 48 hours",
            f"{due_soon_count} tasks are due within the next 48 hours "
            f"({due_today['count']} today, {due_tomorrow['count']} tomorrow).",
            {"due_today": due_today["count"], "due_tomorrow": due_tomorrow["count"],
             "total": due_soon_count,
             "task_ids": [task["id"] for task in soon_rows]},
            [task["id"] for task in soon_rows],
            "Pick the most important one and set aside time for it today.",
        ))

    # ── Rule D: a cluster of tasks left open a long time ──────────────────
    if long_open_count >= RULE_D_LONG_OPEN:
        oldest_open = max(((today - row.created_at.date()).days for row in long_open_rows),
                          default=0)
        insights.append(insight(
            f"long_open_{STALE_DAYS}d", "long_open", "info",
            "Tasks open for a long time",
            f"{long_open_count} tasks have been open for at least {STALE_DAYS} days "
            f"(the oldest for {oldest_open} days).",
            {"long_open_count": long_open_count, "threshold_days": STALE_DAYS,
             "oldest_days_open": oldest_open,
             "task_ids": [row.id for row in long_open_rows]},
            [row.id for row in long_open_rows],
            "Close, reschedule or drop the ones that no longer matter.",
        ))

    insights.sort(key=lambda item: (INSIGHT_SEVERITY[item["severity"]],
                          INSIGHT_ORDER.get(item["type"], 99), item["id"]))
    shown = insights[:limit]
    counts = {"critical": sum(1 for item in insights if item["severity"] == "critical"),
              "warning": sum(1 for item in insights if item["severity"] == "warning"),
              "info": sum(1 for item in insights if item["severity"] == "info")}

    facts = {
        "status": "ok" if shown else "no_data",
        "evaluated_at": evaluated_at,
        "today": today.isoformat(),
        "timezone": timezone_name or "UTC",
        "limit": limit,
        "count": len(insights),
        "shown": len(shown),
        "truncated": len(shown) < len(insights),
        "counts": counts,
        "insights": shown,
        "rules": {
            "high_priority_overdue": "an open task is overdue and high priority",
            "overdue_cluster": f"at least {RULE_B_OVERDUE} open tasks are overdue",
            "due_soon": f"at least {RULE_C_DUE_SOON} open tasks are due today or tomorrow",
            "long_open": f"at least {RULE_D_LONG_OPEN} open tasks have been open "
                         f"{STALE_DAYS}+ days",
        },
    }
    if not shown:
        facts["message"] = ("No significant task-related insights were found in the "
                            "current data.")
    return facts
