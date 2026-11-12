# Database standards — Nirvaah

Postgres 16 in production, SQLite in tests. Schema defined in
`backend/app/models.py` (SQLAlchemy 2.0 typed models) and created by
`Base.metadata.create_all()` at startup (`main.py:16`).

**There is no migration tool. That is the single biggest schema risk in this
repo** — see §6.

---

## 1. Naming and shape

| Rule | Current state |
|---|---|
| Tables plural, snake_case | ✅ `transactions`, `chat_conversations`, `journal_entries` |
| Primary key `id` | ✅ |
| Money tables use integer ids | ✅ `transactions`, `budgets`, `goals`, `investments`, `liabilities` |
| Life tables use client-generated `uuid4` string ids | ✅ `notes`, `tasks`, `journal_entries` — so an offline client can create and keep the same id |
| Ownership column `user_id` on every table, indexed | ✅ all 12 tables that carry `user_id` (every table except `users`, `chat_focus`) |
| Timestamps `created_at`, `updated_at` | ⚠️ `created_at` everywhere; `updated_at` only on life + chat tables. Money rows have no `updated_at` |
| Column names match the domain | ⚠️ inconsistent: `tasks.text` (a title), `journal_entries.event_date` vs `transactions.txn_date`, `notes.body` vs `journal_entries.description` |

## 2. Types

- **Money is `Float` → Postgres `double precision` — 9 columns** (verified against
  the live database): `transactions.amount`, `budgets.monthly_limit`,
  `goals.target_amount`, `goals.saved_amount`, `investments.invested_amount`,
  `investments.current_value`, `liabilities.outstanding_amount`,
  `liabilities.monthly_emi`, `journal_entries.amount`.
  Floats cannot represent paise exactly; sums drift and reconciliation against a
  bank statement will disagree.
  **Standard for new columns: `Numeric(14, 2)`.** Migrating the existing columns
  is Planned (audit C2) and must happen with a `USING round(x::numeric, 2)` step.
- Dates are `Date` (no time) for business dates, `DateTime` (naive UTC) for audit stamps. Never store a month as a date — `budgets.month` is correctly `String(7)` `YYYY-MM`.
- Free-form JSON (`notes.tags`, `chat_messages.meta`) is `Text` holding a JSON string, not `JSONB`. Acceptable at this size; `JSONB` is preferred when a column must be queried.
- Booleans are `Boolean` with an explicit `default=False`, never nullable.

## 3. Constraints and integrity

Current reality: **foreign keys exist, cascades do not.**

- `ForeignKey("users.id")` on every `user_id` ✅
- `ON DELETE CASCADE` ❌ nowhere — deleting a user orphans every row
- `UNIQUE(user_id, category, month)` on `budgets` ❌ missing → two budgets for the same category+month are possible from both the UI and the assistant
- `UNIQUE` on life records is guaranteed by client ids ✅
- `chat_focus.conversation_id` is a PK but has **no FK to the record it points at** (by design — it can point at a task, note or journal entry) → a deleted record leaves a dangling focus. The assistant handles this gracefully (id lookup fails → honest error) but it should be cleared on delete.

**Standard:** every new relationship gets an explicit `ondelete`; every new
business-unique combination gets a constraint, not an application check.

## 4. Indexing

Today: single-column `ix_<table>_user_id` plus primary keys. Nothing else.

Queries that exist and their needs:

| Query | Needs |
|---|---|
| month/date-range filters on transactions | `(user_id, txn_date)` |
| category reports | `(user_id, category, txn_date)` |
| life-record sync fingerprint | `(user_id, updated_at)` on `notes`, `tasks`, `journal_entries` |
| `deletions?kind=` | `(user_id, kind)` |
| `chat_messages` by conversation | `(conversation_id, id)` — `conversation_id` is indexed, good |

**Standard:** add an index in the same change that introduces the query pattern,
and verify with `EXPLAIN (ANALYZE, BUFFERS)` on real data before claiming a win.

## 5. Access rules in code

1. Every query filters by `user_id` (or goes through `owned()`), including aggregates.
2. Writes that report success must read back what they wrote — `agent/execution.py` is the reference implementation (`expire_all()` then `db.get`).
3. Sessions are per-request (`get_db`); no session is shared across threads.
4. `db.commit()` is called once per unit of work; a handler that commits twice must justify it.
5. Bulk operations do not exist yet — if one is added, it commits per record so one failure cannot roll back a user's whole batch silently.

## 6. Migrations (Planned, highest priority)

`create_all()` creates missing **tables**; it never alters existing ones. The
`chat_focus` table appeared correctly because it was new. A column add, rename or
type change would silently not apply and fail at runtime.

Adopted plan:
1. Introduce Alembic with `alembic init backend/migrations`.
2. Baseline revision that reproduces the current schema exactly (`--autogenerate` then hand-check against `models.py`).
3. `alembic upgrade head` runs before the app starts (entrypoint), replacing `create_all` in production.
4. Every schema change ships as a revision in the same PR as the model change.
5. SQLite stays for tests only; migrations are verified against Postgres.

## 7. Backups and recovery

- `backup/backup.sh` dumps with `pg_dump -Fc`, checksums the archive, uploads only when the bytes changed, and **restores into a scratch database to verify** row counts before considering the backup good.
- Retention: `BACKUP_RETENTION_DAYS=14` daily plus the 1st of each month for 12 months.
- Offsite target: S3 (`nirvaah-backups-*`), server-side encrypted, public access blocked, versioned.
- Restore drill (must be run before any release that touches schema):
  `psql -c 'CREATE DATABASE drill'` → `pg_restore -d drill <latest>` → compare table counts.

## 8. Test data

- Tests build their own SQLite database from `models.Base.metadata` in `tests/conftest.py`; they never touch `finance.db` or the container's Postgres.
- Any test user seeded against a real database must be deleted afterwards, and the real user's row counts recorded before and after (this was done for the assistant work: users=1, transactions=754, tasks=5).
