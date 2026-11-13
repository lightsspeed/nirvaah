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

from sqlalchemy import case, func
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
