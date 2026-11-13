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
A file whose first lines say ``-- dialect: postgresql`` is skipped on other engines
and may contain several statements; portable files stay one statement each.

A portable file is executed as a single statement, which keeps it valid on both
PostgreSQL and the SQLite database the tests use. A dialect-scoped file is handed to
the driver as-is and may hold several statements; it runs inside the same transaction.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
LOCK_KEY = 727101  # arbitrary, stable: "nirvaah schema migrations"

# A file may declare `-- dialect: postgresql` in its first lines. It is then only
# applied to that engine, so the SQLite database the tests use can skip DDL that
# only PostgreSQL understands (ALTER COLUMN … TYPE, DO blocks, CHECK constraints).
DIALECT_MARKER = "-- dialect:"


class MigrationError(RuntimeError):
    """A migration file failed. The batch is rolled back; nothing is recorded."""



def _directory(directory: Path | None) -> Path:
    return Path(directory) if directory is not None else MIGRATIONS_DIR


def available(directory: Path | None = None) -> list[Path]:
    """Every migration file, in the order they must be applied."""
    return sorted(p for p in _directory(directory).glob("*.sql") if p.is_file())


def dialect_of(path: Path) -> str | None:
    """The dialect a migration declares, or None when it is portable."""
    try:
        head = path.read_text(encoding="utf-8").splitlines()[:5]
    except OSError:
        return None
    for line in head:
        stripped = line.strip().lower()
        if stripped.startswith(DIALECT_MARKER):
            return stripped.split(":", 1)[1].strip() or None
    return None


def applies_to(path: Path, dialect: str) -> bool:
    declared = dialect_of(path)
    return declared is None or declared == dialect


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
    """Files this engine still needs, ignoring ones written for another dialect."""
    done = applied(engine, directory)
    return [p for p in available(directory)
            if p.name not in done and applies_to(p, engine.dialect.name)]


def apply(engine: Engine, directory: Path | None = None) -> list[str]:
    """Apply pending migrations atomically; returns the versions applied now."""
    with engine.begin() as conn:
        # Lock first: two runners starting together would otherwise race to create
        # the bookkeeping table itself and the loser would die on a duplicate type.
        # The lock is transaction-scoped, so it covers the DDL below as well.
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        _ensure_bookkeeping(conn)
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        dialect = engine.dialect.name
        todo = [p for p in available(directory)
                if p.name not in done and applies_to(p, dialect)]
        for path in todo:
            # Straight to the driver cursor: a migration is raw SQL, and psycopg
            # would read the '%' in a RAISE NOTICE format string as a placeholder.
            # The cursor shares the connection, so the file stays inside the
            # transaction the runner opened.
            cursor = conn.connection.driver_connection.cursor()
            try:
                cursor.execute(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise MigrationError(f"{path.name} failed: {exc}") from exc
            finally:
                cursor.close()
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
