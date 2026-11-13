-- Task 21/23: transaction month filters are now half-open date ranges
-- (txn_date >= month_start AND txn_date < next_month_start). Without this index the
-- planner still reads every row of the user to find one month.
--
-- One statement per file: the runner executes each file as a single statement so the
-- same migration applies on PostgreSQL and on the SQLite database the tests use.
CREATE INDEX IF NOT EXISTS ix_transactions_user_id_txn_date
    ON transactions (user_id, txn_date);
