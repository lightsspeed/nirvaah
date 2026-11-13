"""Deleting a conversation has to take its focus record with it.

`chat_focus` references `chat_conversations(id)` with no ON DELETE action, exactly
like the production schema. SQLite ignores foreign keys unless they are switched
on, so these tests build their own engine with `PRAGMA foreign_keys=ON` — without
that the original bug is invisible here even though Postgres rejects the delete.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app import models
from app.agent import api as agent_api
from app.database import Base


@pytest.fixture()
def fkdb(tmp_path):
    """A session whose engine enforces foreign keys the way PostgreSQL does."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fk.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):  # noqa: ANN001 - sqlalchemy hook
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def owner(fkdb):
    row = models.User(name="Delete Test", email="delete@local.dev", password_hash="x")
    fkdb.add(row)
    fkdb.commit()
    fkdb.refresh(row)
    return row


def _conversation(db, user, conversation_id, *, focus=None, messages=2):
    # The conversation is committed first: without relationship() declarations
    # SQLAlchemy cannot order the inserts, and the focus row is a child of it.
    db.add(models.Conversation(id=conversation_id, user_id=user.id, title=f"Conversation {conversation_id}"))
    db.commit()
    for i in range(messages):
        db.add(models.ChatMessage(
            conversation_id=conversation_id, user_id=user.id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"message {i}", meta="{}",
        ))
    if focus is not None:
        db.add(models.ChatFocus(
            conversation_id=conversation_id,
            entity_type=focus[0], entity_id=focus[1], label="task 1", operation="update",
        ))
    db.commit()
    return conversation_id


def _count(db, model, **filters):
    query = db.query(model)
    for column, value in filters.items():
        query = query.filter(getattr(model, column) == value)
    return query.count()


def test_delete_conversation_with_focus_succeeds(fkdb, owner):
    """The regression: the focus row used to make the delete fail outright."""
    _conversation(fkdb, owner, "conv-focus", focus=("task", "task-1"))

    assert agent_api.delete_conversation("conv-focus", fkdb, owner) == {"deleted": True}

    assert _count(fkdb, models.Conversation, id="conv-focus") == 0
    assert _count(fkdb, models.ChatFocus, conversation_id="conv-focus") == 0


def test_delete_conversation_without_focus_succeeds(fkdb, owner):
    _conversation(fkdb, owner, "conv-plain")

    assert agent_api.delete_conversation("conv-plain", fkdb, owner) == {"deleted": True}
    assert _count(fkdb, models.Conversation, id="conv-plain") == 0


def test_delete_conversation_removes_its_messages(fkdb, owner):
    _conversation(fkdb, owner, "conv-msgs", focus=("note", "note-9"), messages=4)
    assert _count(fkdb, models.ChatMessage, conversation_id="conv-msgs") == 4

    agent_api.delete_conversation("conv-msgs", fkdb, owner)

    assert _count(fkdb, models.ChatMessage, conversation_id="conv-msgs") == 0
    # messages belonging to another conversation are not touched
    assert _count(fkdb, models.ChatMessage) == 0


def test_delete_leaves_other_conversations_and_focus_alone(fkdb, owner):
    _conversation(fkdb, owner, "conv-gone", focus=("task", "task-1"))
    _conversation(fkdb, owner, "conv-keep", focus=("note", "note-2"), messages=3)

    agent_api.delete_conversation("conv-gone", fkdb, owner)

    assert _count(fkdb, models.Conversation) == 1
    assert _count(fkdb, models.Conversation, id="conv-keep") == 1
    assert _count(fkdb, models.ChatMessage, conversation_id="conv-keep") == 3
    kept = fkdb.get(models.ChatFocus, "conv-keep")
    assert kept is not None and kept.entity_id == "note-2"


def test_delete_is_atomic_when_the_conversation_is_unknown(fkdb, owner):
    """Nonexistent id keeps the existing 404 and removes nothing."""
    _conversation(fkdb, owner, "conv-existing", focus=("task", "task-3"), messages=1)

    with pytest.raises(HTTPException) as excinfo:
        agent_api.delete_conversation("does-not-exist", fkdb, owner)

    assert excinfo.value.status_code == 404
    assert _count(fkdb, models.Conversation, id="conv-existing") == 1
    assert _count(fkdb, models.ChatMessage, conversation_id="conv-existing") == 1
    assert _count(fkdb, models.ChatFocus, conversation_id="conv-existing") == 1
