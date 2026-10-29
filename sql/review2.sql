-- =====================================================================================
-- FinLedger-AI — Review 2: joins, subqueries, views, procedures, functions, cursors, triggers
-- Run AFTER review1.sql on the same database (it uses the Review 1 dataset):
--   psql -d finledger_review -f ../sql/review2.sql
-- =====================================================================================
\set ON_ERROR_STOP off
\pset null ''

-- psql variables for the accounts used below
SELECT id AS rahul_sav  FROM accounts WHERE account_number = 'INR-SAV-3BD2762D' \gset
SELECT id AS rahul_cur  FROM accounts WHERE account_number = 'INR-CUR-5009D7C0' \gset
SELECT id AS ananya_sav FROM accounts WHERE account_number = 'INR-SAV-81A4C0E2' \gset
SELECT id AS vikram_sav FROM accounts WHERE account_number = 'INR-SAV-C47E19B5' \gset
SELECT id AS arjun_sav  FROM accounts WHERE account_number = 'INR-SAV-7A5F0C93' \gset
SELECT id AS rahul_user FROM users WHERE username = 'rahul_sharma' \gset
SELECT id AS ananya_user FROM users WHERE username = 'ananya_iyer' \gset
SELECT id AS vikram_user FROM users WHERE username = 'vikram_mehta' \gset
SELECT id AS arjun_user FROM users WHERE username = 'arjun_nair' \gset
SELECT id AS admin_user FROM users WHERE username = 'admin_system' \gset

\echo '\n===== 1. Stored procedure sp_transfer_funds: three customer transfers ====='
SELECT sp_transfer_funds(:'rahul_user',  'r2-k1', repeat('a', 64), :'rahul_sav',  :'ananya_sav', 25000.00, 'Rent share') AS transfer_1;
SELECT sp_transfer_funds(:'ananya_user', 'r2-k2', repeat('b', 64), :'ananya_sav', :'vikram_sav', 12000.00, 'Concert tickets') AS transfer_2;
SELECT sp_transfer_funds(:'vikram_user', 'r2-k3', repeat('c', 64), :'vikram_sav', :'rahul_cur',   5000.00, 'Payback') AS transfer_3;

\echo '--- refused by the procedure (expected ERRORs): frozen source, insufficient funds, not the owner'
SELECT sp_transfer_funds(:'arjun_user', 'r2-k4', repeat('d', 64), :'arjun_sav', :'rahul_sav', 100.00, NULL);
SELECT sp_transfer_funds(:'rahul_user', 'r2-k5', repeat('e', 64), :'rahul_cur', :'ananya_sav', 9999999.00, NULL);
SELECT sp_transfer_funds(:'rahul_user', 'r2-k6', repeat('f', 64), :'ananya_sav', :'rahul_sav', 10.00, NULL);

\echo '--- the same idempotency key cannot be used twice by one sender (expected ERROR)'
SELECT sp_transfer_funds(:'rahul_user', 'r2-k1', repeat('a', 64), :'rahul_sav', :'ananya_sav', 25000.00, 'Rent share');

\echo '\n===== 2. JOINs ====='
\echo '--- INNER JOIN across four tables: who sent what to whom'
SELECT us.username AS sender, sa.account_number AS from_account, da.account_number AS to_account,
       dc.full_name AS recipient, t.amount, t.status
  FROM transfer_requests t
  JOIN users     us ON us.id = t.source_user_id
  JOIN accounts  sa ON sa.id = t.source_account_id
  JOIN accounts  da ON da.id = t.destination_account_id
  JOIN customers dc ON dc.id = da.customer_id
 ORDER BY t.created_at;

\echo '--- LEFT JOIN: every account with its owner (the clearing account has none)'
SELECT a.account_number, a.account_type, COALESCE(c.full_name, '(bank internal)') AS owner
  FROM accounts a LEFT JOIN customers c ON c.id = a.customer_id
 ORDER BY a.account_number;

\echo '--- SELF JOIN: pair the DEBIT and CREDIT legs of each posting'
SELECT t.transaction_type, d_acc.account_number AS debited, c_acc.account_number AS credited, d.amount
  FROM ledger_entries d
  JOIN ledger_entries c ON c.transaction_id = d.transaction_id AND c.entry_type = 'CREDIT'
  JOIN ledger_transactions t ON t.id = d.transaction_id
  JOIN accounts d_acc ON d_acc.id = d.account_id
  JOIN accounts c_acc ON c_acc.id = c.account_id
 WHERE d.entry_type = 'DEBIT'
 ORDER BY t.created_at, c.sequence_num;

\echo '--- RIGHT JOIN + GROUP BY: products and how many investments each has (zero so far)'
SELECT p.code, COUNT(i.id) AS investments
  FROM investments i RIGHT JOIN financial_products p ON p.id = i.product_id
 GROUP BY p.code ORDER BY p.code;

\echo '\n===== 3. Subqueries ====='
\echo '--- scalar subquery: accounts holding more than the average customer balance'
SELECT account_number, cached_balance
  FROM accounts
 WHERE account_type <> 'INTERNAL_CLEARING'
   AND cached_balance > (SELECT AVG(cached_balance) FROM accounts WHERE account_type <> 'INTERNAL_CLEARING')
 ORDER BY cached_balance DESC;

\echo '--- correlated subquery: each customer''s largest account'
SELECT c.full_name, a.account_number, a.cached_balance
  FROM customers c JOIN accounts a ON a.customer_id = c.id
 WHERE a.cached_balance = (SELECT MAX(a2.cached_balance) FROM accounts a2 WHERE a2.customer_id = c.id)
 ORDER BY c.full_name;

\echo '--- NOT EXISTS: customers who have never sent a transfer'
SELECT c.full_name FROM customers c
 WHERE NOT EXISTS (SELECT 1 FROM transfer_requests t WHERE t.source_user_id = c.user_id)
 ORDER BY c.full_name;

\echo '--- IN with a subquery: accounts that received money from Rahul'
SELECT account_number FROM accounts
 WHERE id IN (SELECT destination_account_id FROM transfer_requests WHERE source_user_id = :'rahul_user')
 ORDER BY 1;

\echo '\n===== 4. Views ====='
CREATE OR REPLACE VIEW v_customer_summary AS
SELECT c.full_name, u.username, c.kyc_status,
       COUNT(a.id)                                  AS accounts,
       COALESCE(SUM(a.cached_balance), 0)           AS net_worth,
       (SELECT COUNT(*) FROM transfer_requests t WHERE t.source_user_id = u.id AND t.status = 'POSTED') AS transfers_sent
  FROM customers c
  JOIN users u ON u.id = c.user_id
  LEFT JOIN accounts a ON a.customer_id = c.id
 GROUP BY c.id, c.full_name, u.id, u.username, c.kyc_status;

SELECT * FROM v_customer_summary ORDER BY net_worth DESC;

\echo '--- statement view with running balance (window function inside the view)'
SELECT created_at::time(0) AS at, transaction_type, entry_type, amount, running_balance, counterparty
  FROM v_account_statement WHERE account_id = :'rahul_sav'
 ORDER BY created_at, sequence_num;

\echo '--- reconciliation view: cached_balance must equal the ledger'
SELECT account_number, cached_balance, ledger_balance, discrepancy FROM v_account_reconciliation ORDER BY account_number;

\echo '\n===== 5. Admin correction with sp_reverse_transfer ====='
SELECT id AS rent_transfer FROM transfer_requests WHERE idempotency_key = 'r2-k1' \gset
SELECT sp_reverse_transfer(:'rent_transfer', :'admin_user', 'Customer sent rent to the wrong account') AS reversal_txn;
SELECT status FROM transfer_requests WHERE id = :'rent_transfer';
\echo '--- a second reversal is refused (expected ERROR)'
SELECT sp_reverse_transfer(:'rent_transfer', :'admin_user', 'again');
\echo '--- and only an admin may reverse (expected ERROR)'
SELECT sp_reverse_transfer(:'rent_transfer', :'rahul_user', 'self-service');

\echo '\n===== 6. User-defined functions ====='
CREATE OR REPLACE FUNCTION fn_mask_account(p_number VARCHAR) RETURNS VARCHAR
LANGUAGE sql IMMUTABLE AS $$
    SELECT LPAD(RIGHT(p_number, 4), LENGTH(p_number), 'X')
$$;

CREATE OR REPLACE FUNCTION fn_customer_net_worth(p_username VARCHAR) RETURNS NUMERIC(15,2)
LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_total NUMERIC(15,2);
BEGIN
    SELECT COALESCE(SUM(a.cached_balance), 0) INTO v_total
      FROM accounts a JOIN customers c ON c.id = a.customer_id JOIN users u ON u.id = c.user_id
     WHERE u.username = p_username;
    RETURN v_total;
END;
$$;

SELECT account_number, fn_mask_account(account_number) AS masked FROM accounts WHERE customer_id IS NOT NULL ORDER BY 1;
SELECT username, fn_customer_net_worth(username) AS net_worth FROM users WHERE role = 'CUSTOMER' ORDER BY 2 DESC;

\echo '\n===== 7. Cursor: projected maturity value of every product (explicit cursor in PL/pgSQL) ====='
DO $$
DECLARE
    cur_products CURSOR FOR
        SELECT code, min_amount, annual_yield_rate, term_months FROM financial_products WHERE is_active ORDER BY code;
    rec        RECORD;
    v_maturity NUMERIC(15,2);
    v_count    INTEGER := 0;
BEGIN
    OPEN cur_products;
    LOOP
        FETCH cur_products INTO rec;
        EXIT WHEN NOT FOUND;
        v_maturity := ROUND(rec.min_amount * POWER(1 + rec.annual_yield_rate / 400, rec.term_months / 3.0), 2);
        RAISE NOTICE '% : % invested for % months at % %% (quarterly compounding) -> %',
            rec.code, rec.min_amount, rec.term_months, rec.annual_yield_rate, v_maturity;
        v_count := v_count + 1;
    END LOOP;
    CLOSE cur_products;
    RAISE NOTICE '% products processed', v_count;
END;
$$;

\echo '\n===== 8. Triggers ====='
\echo '--- triggers that protect the ledger'
SELECT event_object_table AS table_name, trigger_name, action_timing AS timing,
       string_agg(event_manipulation, ' OR ' ORDER BY event_manipulation) AS events
  FROM information_schema.triggers
 WHERE trigger_schema = 'public'
 GROUP BY event_object_table, trigger_name, action_timing
 ORDER BY 1, 2;

\echo '--- a new trigger: keep customers.updated_at current automatically'
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_customers_touch ON customers;
CREATE TRIGGER trg_customers_touch BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

UPDATE customers SET phone = '+91-9000000001' WHERE full_name = 'Sneha Kapoor';
SELECT full_name, phone, updated_at > created_at AS touched FROM customers WHERE full_name = 'Sneha Kapoor';

\echo '--- the audit trail is append-only (expected ERROR)'
UPDATE audit_logs SET action = 'TAMPERED';

\echo '\n===== 9. Final proof: books balance and the system total is zero ====='
SELECT COUNT(*) FILTER (WHERE discrepancy <> 0) AS accounts_out_of_balance,
       SUM(cached_balance)                       AS system_total
  FROM v_account_reconciliation;
