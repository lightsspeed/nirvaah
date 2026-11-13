"""Apply the ordered SQL files in ``migrations/`` once each.

``Base.metadata.create_all()`` only creates missing *tables*; it never adds an index
to a table that already exists. Schema changes therefore ship as numbered SQL files
here and are applied deliberately:

    python -m app.migrate

Nothing runs at application startup, so a container start can never issue DDL
against a live database. Each run applies every pending file inside **one**
transaction and records it in ``schema_migrations``; a second run is a no-op. On
PostgreSQL a failure rolls the whole batch back (transactional DDL) and a
transaction-scoped advisory lock keeps two concurrent runners from double-applying.
SQLite's driver commits DDL itself, so keep every file idempotent (``IF NOT EXISTS``).

Files are executed as a single statement each, which keeps them portable (PostgreSQL
and the SQLite database the tests use). Put one statement per file.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 727101  # arbitrary, stable: "nirvaah schema migrations"


def _directory(directory: Path | None) -> Path:
    return Path(directory) if directory is not None else MIGRATIONS_DIR


def available(directory: Path | None = None) -> list[Path]:
    """Every migration file, in the order they must be applied."""
    return sorted(p for p in _directory(directory).glob("*.sql") if p.is_file())


def _ensure_bookkeeping(conn) -> None:
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    ))


def applied(engine: Engine, directory: Path | None = None) -> set[str]:
    """Versions already recorded for this database."""
    with engine.begin() as conn:
        _ensure_bookkeeping(conn)
        return {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}


def pending(engine: Engine, directory: Path | None = None) -> list[Path]:
    done = applied(engine, directory)
    return [p for p in available(directory) if p.name not in done]


def apply(engine: Engine, directory: Path | None = None) -> list[str]:
    """Apply pending migrations atomically; returns the versions applied now."""
    with engine.begin() as conn:
        _ensure_bookkeeping(conn)
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        todo = [p for p in available(directory) if p.name not in done]
        for path in todo:
            conn.execute(text(path.read_text(encoding="utf-8")))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": path.name},
            )
    return [p.name for p in todo]


def main(argv: list[str] | None = None) -> int:
    from .database import engine

    names = apply(engine)
    if names:
        print(f"applied {len(names)} migration(s): {', '.join(names)}")
    else:
        print("no pending migrations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
