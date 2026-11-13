"""Field coercion shared by the snapshot builder and the mutation executor.

Kept apart from `ai.py` so the executor can import it without a cycle.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime


def money(value) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def inr(value) -> str:
    amount = money(value)
    whole = f"{abs(amount):,.2f}"
    return ("-" if amount < 0 else "") + "₹" + whole


def num(payload: dict, key: str, default=None):
    if key in payload and payload[key] not in (None, ""):
        try:
            return float(payload[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
    if default is not None:
        return default
    raise ValueError(f"{key} is required")


def text(payload: dict, key: str, default=""):
    value = payload.get(key, default)
    return "" if value is None else str(value).strip()


def date_value(payload: dict, key: str, default: date | None = None):
    raw = payload.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    value = str(raw).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{key} must be a date like 2026-11-10")


def month(payload: dict, default: str | None = None, today: date | None = None):
    raw = str(payload.get("month") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        return raw
    if raw:
        raise ValueError("month must look like 2026-11")
    return default or (today or date.today()).strftime("%Y-%m")


def tags(payload: dict):
    values = payload.get("tags") or []
    if isinstance(values, str):
        values = [t.strip().lstrip("#") for t in values.split(",")]
    return json.dumps([str(t).strip().lstrip("#") for t in values if str(t).strip()])


def as_plain(value):
    """A comparable, JSON-safe form of a model attribute."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    return str(value)
