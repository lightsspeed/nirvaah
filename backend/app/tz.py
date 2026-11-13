"""The caller's calendar timezone, as a FastAPI dependency.

Business dates — the day a transaction gets, the month a dashboard opens on — are
the user's calendar, not the server's. The browser sends its IANA zone in
``X-User-Timezone`` (``Intl.DateTimeFormat().resolvedOptions().timeZone``) and the
server converts its own UTC clock into that zone.

Why a header rather than a query parameter: it belongs to the request, not to any
one endpoint's filter, so every date-sensitive route gets it from the same place
without a new parameter on each signature. Why not a stored column: that is a
schema decision with a backfill, and this corrects the defaults without one.

The dependency returns a resolved :class:`datetime.date`, so routes never see the
raw header and cannot mishandle it.

Fallback policy:

* header absent — the pre-existing behaviour, UTC (``DEFAULT_TIMEZONE``). Older
  clients and non-browser callers keep working unchanged.
* header present but unreadable — **HTTP 400**. A typo in a timezone name must not
  quietly become UTC and shift a user's month; it is a request error and it says so.
"""

from datetime import date

from fastapi import Header, HTTPException

from .timeutil import DEFAULT_TIMEZONE, resolve_timezone, today_for_timezone


TIMEZONE_HEADER = "X-User-Timezone"


def user_today(x_user_timezone: str | None = Header(default=None, alias=TIMEZONE_HEADER)) -> date:
    """Today's date in the caller's timezone; UTC when the header is absent."""
    name = (x_user_timezone or "").strip()
    if name and resolve_timezone(name) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown timezone {name!r}. Send an IANA name such as 'Asia/Kolkata', "
            f"or omit {TIMEZONE_HEADER} for {DEFAULT_TIMEZONE}.",
        )
    return today_for_timezone(name)
