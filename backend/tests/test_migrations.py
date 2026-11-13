"""The migration runner applies each SQL file once, atomically."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app import migrate
from app.database import Base


@pytest.fixture()
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _indexes(engine) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}


def test_the_index_migration_is_discovered(engine):
    assert [p.name for p in migrate.available()] == ["0001_transactions_user_id_txn_date_index.sql"]
    assert [p.name for p in migrate.pending(engine)] == ["0001_transactions_user_id_txn_date_index.sql"]


def test_index_migration_applies_and_is_recorded(engine):
    assert "ix_transactions_user_id_txn_date" not in _indexes(engine)

    applied = migrate.apply(engine)

    assert applied == ["0001_transactions_user_id_txn_date_index.sql"]
    assert "ix_transactions_user_id_txn_date" in _indexes(engine)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    assert [r[0] for r in rows] == ["0001_transactions_user_id_txn_date_index.sql"]


def test_second_run_is_a_no_op(engine):
    migrate.apply(engine)

    assert migrate.pending(engine) == []
    assert migrate.apply(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM schema_migrations")).scalar() == 1


def test_a_failing_migration_is_not_recorded_and_stays_pending(engine, tmp_path):
    """A bad file stops the batch without recording it, so a fix re-runs cleanly.

    PostgreSQL rolls the whole batch back (transactional DDL). SQLite's driver
    commits DDL itself, so an earlier file's CREATE INDEX can survive — which is
    exactly why every migration is written with IF NOT EXISTS and re-running is safe.
    """
    bad = tmp_path / "migrations"
    bad.mkdir()
    (bad / "0001_ok.sql").write_text("CREATE INDEX IF NOT EXISTS ix_tmp_ok ON transactions (txn_date);", encoding="utf-8")
    (bad / "0002_bad.sql").write_text("THIS IS NOT SQL;", encoding="utf-8")

    with pytest.raises(SQLAlchemyError):
        migrate.apply(engine, directory=bad)

    with engine.connect() as conn:
        recorded = {r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))}
    assert recorded == set()
    assert migrate.pending(engine, directory=bad) == migrate.available(bad)


def test_create_all_alone_does_not_add_the_index(tmp_path):
    """Why the migration exists: create_all never touches an existing table."""
    engine = create_engine(f"sqlite:///{tmp_path / 'plain.db'}")
    try:
        Base.metadata.create_all(engine)
        assert "ix_transactions_user_id_txn_date" not in _indexes(engine)
    finally:
        engine.dispose()
