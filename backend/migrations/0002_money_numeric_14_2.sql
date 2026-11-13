-- dialect: postgresql
-- Task 25: money is numeric(14,2), not an IEEE-754 double.
--
-- Applied by `python -m app.migrate`, once, in a single transaction under an
-- advisory lock. The preflight block refuses to start if any value cannot be
-- represented, so a bad row fails the migration instead of truncating data.
-- Values with more than two decimals are rounded half-up to paise; the notice
-- reports how many rows that affects.

DO $money_preflight$
DECLARE
    bad_range     integer := 0;
    bad_finite    integer := 0;
    bad_zero      integer := 0;
    needs_round   integer := 0;
BEGIN
    SELECT count(*) INTO bad_range FROM (
        SELECT amount AS v FROM transactions
        UNION ALL SELECT monthly_limit FROM budgets
        UNION ALL SELECT target_amount FROM goals
        UNION ALL SELECT saved_amount FROM goals
        UNION ALL SELECT invested_amount FROM investments
        UNION ALL SELECT current_value FROM investments
        UNION ALL SELECT outstanding_amount FROM liabilities
        UNION ALL SELECT monthly_emi FROM liabilities
        UNION ALL SELECT amount FROM journal_entries
    ) every_money WHERE v IS NOT NULL AND abs(v) >= 1000000000000;

    SELECT count(*) INTO bad_finite FROM (
        SELECT amount AS v FROM transactions
        UNION ALL SELECT monthly_limit FROM budgets
        UNION ALL SELECT target_amount FROM goals
        UNION ALL SELECT saved_amount FROM goals
        UNION ALL SELECT invested_amount FROM investments
        UNION ALL SELECT current_value FROM investments
        UNION ALL SELECT outstanding_amount FROM liabilities
        UNION ALL SELECT monthly_emi FROM liabilities
        UNION ALL SELECT amount FROM journal_entries
    ) every_money WHERE v IS NOT NULL AND v::text IN ('NaN', 'Infinity', '-Infinity');

    SELECT count(*) INTO bad_zero FROM (
        SELECT amount AS v FROM transactions
        UNION ALL SELECT monthly_limit FROM budgets
        UNION ALL SELECT target_amount FROM goals
    ) positive_money WHERE v IS NOT NULL AND round(v::numeric, 2) = 0;

    SELECT count(*) INTO needs_round FROM (
        SELECT amount AS v FROM transactions
        UNION ALL SELECT monthly_limit FROM budgets
        UNION ALL SELECT target_amount FROM goals
        UNION ALL SELECT saved_amount FROM goals
        UNION ALL SELECT invested_amount FROM investments
        UNION ALL SELECT current_value FROM investments
        UNION ALL SELECT outstanding_amount FROM liabilities
        UNION ALL SELECT monthly_emi FROM liabilities
        UNION ALL SELECT amount FROM journal_entries
    ) every_money WHERE v IS NOT NULL AND v <> round(v::numeric, 2);

    IF bad_finite > 0 THEN
        RAISE EXCEPTION 'money migration aborted: % value(s) are NaN or infinite', bad_finite;
    END IF;
    IF bad_range > 0 THEN
        RAISE EXCEPTION 'money migration aborted: % value(s) do not fit numeric(14,2)', bad_range;
    END IF;
    IF bad_zero > 0 THEN
        RAISE EXCEPTION 'money migration aborted: % value(s) are in a positive-only column but round to 0.00', bad_zero;
    END IF;
    RAISE NOTICE 'money migration: % value(s) will be rounded to paise', needs_round;
END
$money_preflight$;

ALTER TABLE transactions    ALTER COLUMN amount             TYPE numeric(14,2) USING round(amount::numeric, 2);
ALTER TABLE budgets         ALTER COLUMN monthly_limit      TYPE numeric(14,2) USING round(monthly_limit::numeric, 2);
ALTER TABLE goals           ALTER COLUMN target_amount      TYPE numeric(14,2) USING round(target_amount::numeric, 2),
                            ALTER COLUMN saved_amount       TYPE numeric(14,2) USING round(saved_amount::numeric, 2);
ALTER TABLE investments     ALTER COLUMN invested_amount    TYPE numeric(14,2) USING round(invested_amount::numeric, 2),
                            ALTER COLUMN current_value      TYPE numeric(14,2) USING round(current_value::numeric, 2);
ALTER TABLE liabilities     ALTER COLUMN outstanding_amount TYPE numeric(14,2) USING round(outstanding_amount::numeric, 2),
                            ALTER COLUMN monthly_emi        TYPE numeric(14,2) USING round(monthly_emi::numeric, 2);
ALTER TABLE journal_entries ALTER COLUMN amount             TYPE numeric(14,2) USING round(amount::numeric, 2);

ALTER TABLE transactions ADD CONSTRAINT transactions_amount_range
    CHECK (amount > 0 AND amount < 1000000000000);
ALTER TABLE budgets ADD CONSTRAINT budgets_monthly_limit_range
    CHECK (monthly_limit > 0 AND monthly_limit < 1000000000000);
ALTER TABLE goals ADD CONSTRAINT goals_target_amount_range
    CHECK (target_amount > 0 AND target_amount < 1000000000000);
ALTER TABLE goals ADD CONSTRAINT goals_saved_amount_range
    CHECK (saved_amount >= 0 AND saved_amount < 1000000000000);
ALTER TABLE investments ADD CONSTRAINT investments_invested_amount_range
    CHECK (invested_amount >= 0 AND invested_amount < 1000000000000);
ALTER TABLE investments ADD CONSTRAINT investments_current_value_range
    CHECK (current_value >= 0 AND current_value < 1000000000000);
ALTER TABLE liabilities ADD CONSTRAINT liabilities_outstanding_amount_range
    CHECK (outstanding_amount >= 0 AND outstanding_amount < 1000000000000);
ALTER TABLE liabilities ADD CONSTRAINT liabilities_monthly_emi_range
    CHECK (monthly_emi >= 0 AND monthly_emi < 1000000000000);
ALTER TABLE journal_entries ADD CONSTRAINT journal_entries_amount_range
    CHECK (amount IS NULL OR (amount >= 0 AND amount < 1000000000000));
