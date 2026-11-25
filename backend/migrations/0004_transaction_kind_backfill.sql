-- dialect: postgresql
-- The first four-type release stored Investments and Savings as expense rows
-- with a dedicated category. They are their own kinds now, so reports and the
-- dedicated pages can see them without treating them as spending. Only rows
-- whose only signal is that category are touched; a real expense is never
-- reclassified. Idempotent: the second run matches nothing.

UPDATE transactions
SET kind = 'investment'
WHERE kind = 'expense' AND lower(category) = 'investments';

UPDATE transactions
SET kind = 'savings'
WHERE kind = 'expense' AND lower(category) = 'savings';
