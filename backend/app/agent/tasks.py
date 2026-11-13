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
from datetime import date, timedelta

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from .. import models


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
