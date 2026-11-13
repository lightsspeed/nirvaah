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
from datetime import UTC, date, datetime, time, timedelta, timezone
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


#: IANA names that browsers still report but modern tzdata keeps only in its
#: `backward` file. Debian 13 ships tzdata *without* that file, so ZoneInfo() cannot
#: resolve them — and Chrome reports India as ``Asia/Calcutta``, not ``Asia/Kolkata``.
#: Without this map a perfectly valid browser request is rejected as unknown.
LEGACY_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Dacca": "Asia/Dhaka",
    "Asia/Thimbu": "Asia/Thimphu",
    "Asia/Chongqing": "Asia/Shanghai",
    "Asia/Chungking": "Asia/Shanghai",
    "Asia/Harbin": "Asia/Shanghai",
    "Asia/Macao": "Asia/Macau",
    "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
    "Europe/Kiev": "Europe/Kyiv",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Godthab": "America/Nuuk",
    "Pacific/Ponape": "Pacific/Pohnpei",
    "Pacific/Truk": "Pacific/Chuuk",
    "US/Eastern": "America/New_York",
    "US/Central": "America/Chicago",
    "US/Mountain": "America/Denver",
    "US/Pacific": "America/Los_Angeles",
}


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
    candidate = LEGACY_ALIASES.get(candidate, candidate)
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


def local_day_bounds(day: date, timezone_name: str | None = None) -> tuple[datetime, datetime]:
    """The UTC instants that bracket one *local* calendar day: [start, end).

    Stored timestamps are naive UTC, but "today", "yesterday" and "this week" are
    the user's dates. A local midnight is not a UTC midnight (IST midnight is
    18:30 UTC the previous day), so a date filter on a timestamp column has to be
    converted once, here, rather than guessed at in a query.
    """
    zone = resolve_timezone(timezone_name) or ZoneInfo(DEFAULT_TIMEZONE)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return (start.astimezone(UTC).replace(tzinfo=None),
            end.astimezone(UTC).replace(tzinfo=None))


def local_range_bounds(start: date, end: date,
                       timezone_name: str | None = None) -> tuple[datetime, datetime]:
    """UTC instants for a local date range, inclusive of both ends."""
    return local_day_bounds(start, timezone_name)[0], local_day_bounds(end, timezone_name)[1]


def iso_utc(value: datetime | None) -> str | None:
    """Serialize a stored timestamp as an explicit UTC instant.

    The database holds naive UTC, so ``isoformat()`` alone emits
    ``2026-11-13T01:36:23`` — and every browser reads that as *local* wall time,
    which is the other half of the date bug. Timestamps leave the API as
    ``2026-11-13T01:36:23.123456Z``: naive values are interpreted as UTC, aware
    values are converted to UTC first, and the result always carries the marker.

    Calendar dates do not come through here — they are ``date`` objects and stay
    ``YYYY-MM-DD`` with no timezone at all.
    """
    if value is None:
        return None
    utc = ZoneInfo(DEFAULT_TIMEZONE)
    value = value.replace(tzinfo=utc) if value.tzinfo is None else value.astimezone(utc)
    return value.isoformat().replace("+00:00", "Z")
