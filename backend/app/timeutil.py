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
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
