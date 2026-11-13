"""The one clock: `app.timeutil.utcnow()`.

Nirvaah stores timestamps as naive UTC. These tests pin that contract down from
both ends — the helper itself, and the ORM defaults that consume it — because a
reviewer reading `utcnow()` cannot tell by eye whether the value is still naive
or whether somebody quietly "fixed" it into an aware datetime.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone

import pytest

from app import models
from app.agent import focus
from app.timeutil import utcnow


TOLERANCE_SECONDS = 60


def _utc_wall_clock() -> datetime:
    """UTC now, stripped to naive, computed independently of the helper."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_returns_a_datetime():
    assert isinstance(utcnow(), datetime)


def test_value_is_naive():
    value = utcnow()
    assert value.tzinfo is None
    assert value.utcoffset() is None


def test_value_tracks_the_current_utc_time():
    before = _utc_wall_clock()
    value = utcnow()
    after = _utc_wall_clock()
    # Bracket the call rather than comparing to a single reading, so a slow CI
    # runner cannot make this flaky.
    assert (
        before - timedelta(seconds=TOLERANCE_SECONDS) <= value <= after + timedelta(seconds=TOLERANCE_SECONDS)
    )


def _local_offset() -> timedelta:
    return datetime.now().astimezone().utcoffset() or timedelta(0)


def test_value_is_not_local_system_time():
    """If the machine is not on UTC, the value must differ from local wall time by exactly the offset."""
    value = utcnow()
    offset = _local_offset()
    drift = (value - datetime.now()).total_seconds()

    if abs(offset.total_seconds()) > 120:
        # e.g. IST: utcnow() must sit `offset` behind local wall time, not level with it.
        assert drift == pytest.approx(-offset.total_seconds(), abs=TOLERANCE_SECONDS)
        assert abs(drift) > 120
    else:
        # The host itself runs on UTC, so local and UTC wall time coincide and this
        # check cannot discriminate. The UTC-anchored assertion above is the real guard.
        assert abs(drift) <= TOLERANCE_SECONDS


def test_helper_emits_no_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        utcnow()
    utcnow_warnings = [w for w in caught if "utcnow" in str(w.message)]
    assert utcnow_warnings == [], [str(w.message) for w in utcnow_warnings]


def test_model_defaults_populate_naive_utc(db, user):
    """Every timestamped model still fills its columns from the shared helper."""
    fresh = models.Task(id="timeutil-task", user_id=user.id, text="Timestamp check")
    focus_row = models.ChatFocus(conversation_id="timeutil-conv")
    journal = models.JournalEntry(id="timeutil-journal", user_id=user.id, title="Timestamp check")
    tombstone = models.Deletion(id="timeutil-deletion", user_id=user.id, kind="tasks")
    db.add_all([fresh, focus_row, journal, tombstone])
    db.commit()

    for row in (fresh, focus_row, journal, tombstone):
        db.refresh(row)

    expected = _utc_wall_clock()
    stamps = {
        "task.created_at": fresh.created_at,
        "task.updated_at": fresh.updated_at,
        "chat_focus.updated_at": focus_row.updated_at,
        "journal.created_at": journal.created_at,
        "journal.updated_at": journal.updated_at,
        "deletion.deleted_at": tombstone.deleted_at,
    }
    for name, value in stamps.items():
        assert isinstance(value, datetime), f"{name} was not populated"
        assert value.tzinfo is None, f"{name} came back timezone-aware"
        assert value.utcoffset() is None, f"{name} came back with an offset"
        assert abs((expected - value).total_seconds()) <= TOLERANCE_SECONDS, f"{name} is not recent UTC"


def test_updated_at_assignment_site_writes_naive_utc(db, user):
    """The focus writer, one of the hand-assigned sites, stores the same shape."""
    focus.set_focus(
        db,
        user,
        "timeutil-focus",
        entity_type="task",
        entity_id="seed-wheel-balancing",
        label="Wheel Balancing",
        operation="update",
    )
    row = db.get(models.ChatFocus, "timeutil-focus")
    assert row is not None
    assert isinstance(row.updated_at, datetime)
    assert row.updated_at.tzinfo is None
    assert abs((_utc_wall_clock() - row.updated_at).total_seconds()) <= TOLERANCE_SECONDS
