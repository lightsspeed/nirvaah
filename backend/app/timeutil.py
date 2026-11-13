"""One clock for the whole backend.

Nirvaah stores every timestamp as naive UTC — the columns are `timestamp without
time zone` and the values they hold are UTC, with no offset attached. That is the
storage contract; this module is the single place that produces that shape.

`datetime.utcnow()` used to do the job and was deprecated in Python 3.12. It is
replaced by an explicitly UTC-anchored value with the tzinfo stripped back off,
so the bytes written to the database are identical to before: still UTC, still
naive, still `tzinfo is None`. Callers must not "improve" this into an aware
datetime — an aware value written into a `timestamp without time zone` column
would be shifted by the database session's timezone.

The second half of this module answers a different question: *whose calendar day
is it?* A timestamp is one instant everywhere; "today" is not. Business dates (a
transaction's day, the month a dashboard opens on) belong to the user, so they are
derived from the caller's IANA timezone, never from the server's clock. The server
keeps its own UTC clock and converts it — a client cannot tell us what today is,
only where they are.
"""

import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


log = logging.getLogger("nirvaah.time")

#: Documented fallback when a request carries no timezone (or a broken one).
#: This is the pre-existing behaviour: the backend container runs on UTC.
DEFAULT_TIMEZONE = "UTC"

#: IANA names we have already complained about, so a bad client cannot flood the log.
_warned: set[str] = set()


def _utc_now() -> datetime:
    """The one place the real clock is read. Tests replace this."""
    return datetime.now(timezone.utc)


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime."""
    return _utc_now().replace(tzinfo=None)


def resolve_timezone(name: str | None) -> ZoneInfo | None:
    """The ZoneInfo for a valid IANA identifier, else None.

    Returning None rather than UTC keeps the substitution visible to the caller:
    an unknown name is a bug in the request, not a fact about the world.
    """
    if not name or not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate or len(candidate) > 64:
        return None
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def today_for_timezone(timezone_name: str | None) -> date:
    """The caller's local calendar date, from the server's own UTC clock.

    A missing name falls back to :data:`DEFAULT_TIMEZONE` (today's behaviour). An
    *invalid* name also falls back, but logs a warning — an unreadable timezone is
    reported, never silently rewritten.
    """
    zone = resolve_timezone(timezone_name)
    if zone is None:
        if timezone_name and timezone_name not in _warned:
            _warned.add(timezone_name)
            log.warning("unknown timezone %r; falling back to %s", timezone_name, DEFAULT_TIMEZONE)
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return _utc_now().astimezone(zone).date()
