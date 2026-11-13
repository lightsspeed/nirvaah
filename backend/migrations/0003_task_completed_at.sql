-- dialect: postgresql
-- Task 29.3: remember when a task was completed.
--
-- Nullable on purpose. Tasks completed before this column existed have no
-- knowable completion date; the migration does not invent one and does not
-- backfill with the time it ran. Those rows keep completed_at = NULL and are
-- excluded from every date-based completion history (see app/agent/tasks.py).
-- Idempotent so a re-run after a partial deploy is safe.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP NULL;
