-- =====================================================================================
-- FinLedger-AI — Review 1: Case Study Analysis & Basic SQL
-- Reproduces every statement in sections 4–8 of the Review 1 report.
--
-- Run against an EMPTY database built from the migrations (do not run scripts/seed.py first):
--   createdb finledger_review
--   cd backend && alembic -x db=finledger_review upgrade head
--   psql -d finledger_review -f ../sql/review1.sql
--
-- Several statements fail ON PURPOSE (constraint and trigger demonstrations), so the
-- script keeps going after an error.
-- =====================================================================================
\set ON_ERROR_STOP off
\pset null ''

\echo '\n===== 4.1 CREATE TABLE — core schema (in scratch schema ddl_check) ====='
CREATE SCHEMA ddl_check;
SET search_path TO ddl_check;

CREATE TABLE users (
    id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username       VARCHAR(50)  NOT NULL UNIQUE,
    email          VARCHAR(255) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    role           VARCHAR(20)  NOT NULL,
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_users_role_valid CHECK (role IN ('CUSTOMER', 'STAFF', 'ADMIN'))
);
CREATE TABLE customers (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL UNIQUE REFERENCES users(id) ON DELETE RESTRICT,
    full_name   VARCHAR(100) NOT NULL,
    phone       VARCHAR(20),
    pan_number  VARCHAR(10),
    kyc_status  VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_customers_kyc_status_valid CHECK (kyc_status IN ('PENDING', 'VERIFIED', 'REJECTED'))
);
CREATE TABLE accounts (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     UUID          REFERENCES customers(id) ON DELETE RESTRICT,  -- NULL for the clearing account
    account_number  VARCHAR(32)   NOT NULL UNIQUE,
    account_type    VARCHAR(20)   NOT NULL,
    currency        VARCHAR(3)    NOT NULL DEFAULT 'INR',
    cached_balance  NUMERIC(15,2) NOT NULL DEFAULT 0.00,
    status          VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE',
    version         INTEGER       NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT chk_accounts_type_valid   CHECK (account_type IN ('SAVINGS','CURRENT','INTERNAL_CLEARING','INVESTMENT')),
    CONSTRAINT chk_accounts_currency_inr CHECK (currency = 'INR'),
    CONSTRAINT chk_accounts_status_valid CHECK (status IN ('ACTIVE','FROZEN','CLOSED')),
    CONSTRAINT chk_accounts_non_negative_balance
        CHECK (account_type = 'INTERNAL_CLEARING' OR cached_balance >= 0.00)
);
CREATE TABLE financial_products (
    id                 UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    name               VARCHAR(100)  NOT NULL,
    code               VARCHAR(32)   NOT NULL UNIQUE,
    product_type       VARCHAR(20)   NOT NULL,
    annual_yield_rate  NUMERIC(5,2)  NOT NULL,
    min_amount         NUMERIC(15,2) NOT NULL,
    term_months        INTEGER       NOT NULL,
    is_active          BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT chk_products_type_valid CHECK (product_type IN ('FIXED_DEPOSIT','RECURRING_DEPOSIT','MUTUAL_FUND','TREASURY_BILL')),
    CONSTRAINT chk_products_yield_positive      CHECK (annual_yield_rate >= 0.00),
    CONSTRAINT chk_products_min_amount_positive CHECK (min_amount > 0.00),
    CONSTRAINT chk_products_term_positive       CHECK (term_months > 0)
);
CREATE TABLE transfer_requests (
    id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key         VARCHAR(64)   NOT NULL,
    source_user_id          UUID          NOT NULL REFERENCES users(id)    ON DELETE RESTRICT,
    request_hash            VARCHAR(64)   NOT NULL,
    source_account_id       UUID          NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    destination_account_id  UUID          NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    amount                  NUMERIC(15,2) NOT NULL,
    currency                VARCHAR(3)    NOT NULL DEFAULT 'INR',
    status                  VARCHAR(20)   NOT NULL,
    failure_reason          TEXT,
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT now(),
    posted_at               TIMESTAMPTZ,
    CONSTRAINT uq_transfers_user_idempotency   UNIQUE (source_user_id, idempotency_key),
    CONSTRAINT chk_transfers_amount_positive   CHECK (amount > 0.00),
    CONSTRAINT chk_transfers_currency_inr      CHECK (currency = 'INR'),
    CONSTRAINT chk_transfers_status_valid      CHECK (status IN ('PENDING','POSTED','FAILED','REVERSED')),
    CONSTRAINT chk_transfers_distinct_accounts CHECK (source_account_id <> destination_account_id)
);
CREATE TABLE ledger_transactions (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    transfer_request_id  UUID         UNIQUE REFERENCES transfer_requests(id) ON DELETE RESTRICT,
    transaction_type     VARCHAR(30)  NOT NULL,
    description          VARCHAR(255) NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_ledger_txn_type_valid CHECK (transaction_type IN
        ('CUSTOMER_TRANSFER','INITIAL_DEPOSIT','CORRECTION_REVERSAL','INVESTMENT_PURCHASE'))
);
CREATE TABLE ledger_entries (
    id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID          NOT NULL REFERENCES ledger_transactions(id) ON DELETE RESTRICT,
    account_id      UUID          NOT NULL REFERENCES accounts(id)            ON DELETE RESTRICT,
    entry_type      VARCHAR(6)    NOT NULL,
    amount          NUMERIC(15,2) NOT NULL,
    sequence_num    SMALLINT      NOT NULL,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT chk_ledger_entry_type_valid      CHECK (entry_type IN ('DEBIT','CREDIT')),
    CONSTRAINT chk_ledger_entry_amount_positive CHECK (amount > 0.00)
);
CREATE TABLE audit_logs (
    id             BIGSERIAL    PRIMARY KEY,
    actor_user_id  UUID         REFERENCES users(id) ON DELETE RESTRICT,
    action         VARCHAR(50)  NOT NULL,
    entity_type    VARCHAR(30)  NOT NULL,
    entity_id      VARCHAR(64)  NOT NULL,
    ip_address     VARCHAR(45),
    user_agent     VARCHAR(255),
    metadata_json  JSONB        NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE TABLE fraud_predictions (
    id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    transfer_request_id  UUID         NOT NULL UNIQUE REFERENCES transfer_requests(id) ON DELETE RESTRICT,
    model_version        VARCHAR(30)  NOT NULL,
    risk_score           NUMERIC(5,4) NOT NULL,
    decision             VARCHAR(20)  NOT NULL,
    rule_flags           JSONB        NOT NULL DEFAULT '[]',
    feature_snapshot     JSONB        NOT NULL DEFAULT '{}',
    explanation          TEXT         NOT NULL,
    review_status        VARCHAR(20)  NOT NULL DEFAULT 'PENDING',
    reviewed_by_user_id  UUID         REFERENCES users(id) ON DELETE RESTRICT,
    review_notes         TEXT,
    reviewed_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_fraud_risk_score_range    CHECK (risk_score BETWEEN 0.0000 AND 1.0000),
    CONSTRAINT chk_fraud_decision_valid      CHECK (decision IN ('LOW_RISK','MEDIUM_RISK','HIGH_RISK')),
    CONSTRAINT chk_fraud_review_status_valid CHECK (review_status IN ('PENDING','CLEARED','CONFIRMED_FRAUD','ESCALATED'))
);
CREATE INDEX idx_ledger_entries_account_created_seq
    ON ledger_entries (account_id, created_at DESC, sequence_num DESC);
CREATE INDEX idx_transfers_status_created ON transfer_requests (status, created_at DESC);
CREATE INDEX idx_fraud_pending_queue ON fraud_predictions (risk_score DESC, created_at DESC)
    WHERE review_status = 'PENDING';

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'ddl_check' ORDER BY table_name;

\echo '\n===== Dropping the scratch schema removes the nine tables ====='
SET search_path TO public;
DROP SCHEMA ddl_check CASCADE;

\echo '\n===== 4.2 Verifying a table definition ====='
\d accounts

\echo '\n===== 4.4 TRUNCATE is refused on append-only tables (expected ERROR) ====='
TRUNCATE TABLE ledger_entries;

\echo '\n===== 6.1 INSERT — users ====='
INSERT INTO users (id, username, email, password_hash, role, is_active) VALUES
 (gen_random_uuid(), 'admin_system',       'admin@finledger.in',  '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'ADMIN',    TRUE),
 (gen_random_uuid(), 'priya_investigator', 'priya@finledger.in',  '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'STAFF',    TRUE),
 (gen_random_uuid(), 'rahul_sharma',       'rahul@example.in',    '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'CUSTOMER', TRUE),
 (gen_random_uuid(), 'ananya_iyer',        'ananya@example.in',   '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'CUSTOMER', TRUE),
 (gen_random_uuid(), 'vikram_mehta',       'vikram@example.in',   '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'CUSTOMER', TRUE),
 (gen_random_uuid(), 'sneha_kapoor',       'sneha@example.in',    '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'CUSTOMER', TRUE),
 (gen_random_uuid(), 'arjun_nair',         'arjun@example.in',    '$argon2id$v=19$m=65536,t=3,p=4$demo-hash', 'CUSTOMER', TRUE);
SELECT username, email, role, is_active FROM users ORDER BY role, username;

\echo '\n===== 6.1 INSERT … SELECT — customers ====='
INSERT INTO customers (id, user_id, full_name, phone, pan_number, kyc_status, created_at)
SELECT gen_random_uuid(), u.id, v.full_name, v.phone, v.pan, 'PENDING', v.created::timestamptz
FROM (VALUES
  ('rahul_sharma', 'Rahul Sharma', '+91-9876543210', 'ABCDE1234F', '2026-01-12 10:15'),
  ('ananya_iyer',  'Ananya Iyer',  '+91-9845012345', 'BKXPI4521K', '2026-02-03 11:40'),
  ('vikram_mehta', 'Vikram Mehta', '+91-9820098200', 'CMNPM7788Q', '2026-03-21 16:05'),
  ('sneha_kapoor', 'Sneha Kapoor', NULL,             'DKZPK1029L', '2026-06-09 09:30'),
  ('arjun_nair',   'Arjun Nair',   '+91-9447001122', NULL,         '2026-09-28 14:55')
) AS v(username, full_name, phone, pan, created)
JOIN users u ON u.username = v.username;
SELECT full_name, phone, pan_number, kyc_status, created_at::date AS joined FROM customers ORDER BY created_at;

\echo '\n===== 6.1 INSERT — clearing account + customer accounts ====='
-- The internal clearing account has no customer (customer_id is NULL).
INSERT INTO accounts (id, customer_id, account_number, account_type, currency, cached_balance, status, version)
VALUES (gen_random_uuid(), NULL, 'INR-SYS-CLEARING', 'INTERNAL_CLEARING', 'INR', 0.00, 'ACTIVE', 1);

INSERT INTO accounts (id, customer_id, account_number, account_type, currency, cached_balance, status, version, created_at)
SELECT gen_random_uuid(), c.id, v.acc_no, v.acc_type, 'INR', 0.00, 'ACTIVE', 1, c.created_at
FROM (VALUES
  ('Rahul Sharma', 'INR-SAV-3BD2762D', 'SAVINGS'),
  ('Rahul Sharma', 'INR-CUR-5009D7C0', 'CURRENT'),
  ('Ananya Iyer',  'INR-SAV-81A4C0E2', 'SAVINGS'),
  ('Vikram Mehta', 'INR-SAV-C47E19B5', 'SAVINGS'),
  ('Vikram Mehta', 'INR-CUR-9F0D3A71', 'CURRENT'),
  ('Sneha Kapoor', 'INR-SAV-2E6B8D14', 'SAVINGS'),
  ('Arjun Nair',   'INR-SAV-7A5F0C93', 'SAVINGS')
) AS v(full_name, acc_no, acc_type)
JOIN customers c ON c.full_name = v.full_name;
SELECT account_number, account_type, currency, cached_balance, status FROM accounts ORDER BY account_number;

\echo '\n===== 6.1 INSERT — financial products ====='
INSERT INTO financial_products (id, name, code, product_type, annual_yield_rate, min_amount, term_months, is_active) VALUES
 (gen_random_uuid(), '12-Month Standard Fixed Deposit',       'FD-12M-STD',    'FIXED_DEPOSIT',     7.10, 10000.00, 12, TRUE),
 (gen_random_uuid(), '36-Month High-Yield Fixed Deposit',     'FD-36M-HY',     'FIXED_DEPOSIT',     7.50, 25000.00, 36, TRUE),
 (gen_random_uuid(), '24-Month Systematic Recurring Deposit', 'RD-24M-SYS',    'RECURRING_DEPOSIT', 6.80,  5000.00, 24, TRUE),
 (gen_random_uuid(), 'Simulated Liquid Debt Growth Fund',     'MF-LIQ-GROWTH', 'MUTUAL_FUND',       6.50,  1000.00,  3, TRUE),
 (gen_random_uuid(), '182-Day Sovereign Treasury Bill',       'TB-182D-SOV',   'TREASURY_BILL',     6.90, 10000.00,  6, TRUE);
SELECT code, product_type, annual_yield_rate, min_amount, term_months FROM financial_products ORDER BY code;

\echo '\n===== 6.2 INSERT inside a transaction: a balanced opening deposit ====='
BEGIN;
WITH txn AS (
    INSERT INTO ledger_transactions (id, transaction_type, description)
    VALUES (gen_random_uuid(), 'INITIAL_DEPOSIT', 'Opening deposit INR-SAV-3BD2762D')
    RETURNING id
)
INSERT INTO ledger_entries (id, transaction_id, account_id, entry_type, amount, sequence_num)
SELECT gen_random_uuid(), txn.id, a.id, leg.entry_type, 150000.00, leg.seq
FROM txn
CROSS JOIN (VALUES ('INR-SYS-CLEARING', 'DEBIT', 1), ('INR-SAV-3BD2762D', 'CREDIT', 2)) AS leg(acc_no, entry_type, seq)
JOIN accounts a ON a.account_number = leg.acc_no;
UPDATE accounts SET cached_balance = cached_balance - 150000.00, version = version + 1, updated_at = now()
WHERE account_number = 'INR-SYS-CLEARING';
UPDATE accounts SET cached_balance = cached_balance + 150000.00, version = version + 1, updated_at = now()
WHERE account_number = 'INR-SAV-3BD2762D';
COMMIT;

\echo '\n===== 6.3 INSERT … SELECT: a batch of opening deposits ====='
BEGIN;
CREATE TEMP TABLE opening (acc_no VARCHAR(32), amount NUMERIC(15,2)) ON COMMIT DROP;
INSERT INTO opening VALUES
  ('INR-CUR-5009D7C0',  40000.00), ('INR-SAV-81A4C0E2', 220000.00), ('INR-SAV-C47E19B5', 85000.00),
  ('INR-CUR-9F0D3A71', 310000.00), ('INR-SAV-2E6B8D14',  64500.00), ('INR-SAV-7A5F0C93', 12000.00);
INSERT INTO ledger_transactions (id, transaction_type, description)
VALUES ('6f1d2c3b-0000-4000-8000-000000000001', 'INITIAL_DEPOSIT', 'Opening deposits batch #1');
INSERT INTO ledger_entries (id, transaction_id, account_id, entry_type, amount, sequence_num)
SELECT gen_random_uuid(), '6f1d2c3b-0000-4000-8000-000000000001'::uuid, a.id, 'CREDIT', o.amount,
       (ROW_NUMBER() OVER (ORDER BY o.acc_no) + 1)::smallint
FROM opening o JOIN accounts a ON a.account_number = o.acc_no
UNION ALL
SELECT gen_random_uuid(), '6f1d2c3b-0000-4000-8000-000000000001'::uuid, a.id, 'DEBIT', (SELECT SUM(amount) FROM opening), 1::smallint
FROM accounts a WHERE a.account_number = 'INR-SYS-CLEARING';
UPDATE accounts a SET cached_balance = a.cached_balance + o.amount, version = a.version + 1, updated_at = now()
FROM opening o WHERE a.account_number = o.acc_no;
UPDATE accounts SET cached_balance = cached_balance - (SELECT SUM(amount) FROM opening),
       version = version + 1, updated_at = now()
WHERE account_number = 'INR-SYS-CLEARING';
COMMIT;
SELECT account_number, account_type, cached_balance FROM accounts ORDER BY account_number;

\echo '\n===== 5.1 Constraint inventory ====='
SELECT tc.table_name, tc.constraint_type, COUNT(*) AS how_many
FROM information_schema.table_constraints tc
WHERE tc.table_schema = 'public'
  AND tc.table_name IN ('users','customers','accounts','financial_products','transfer_requests',
                        'ledger_transactions','ledger_entries','audit_logs','fraud_predictions')
  AND tc.constraint_type IN ('PRIMARY KEY','FOREIGN KEY','UNIQUE','CHECK')
  AND tc.constraint_name NOT LIKE '%not_null'
GROUP BY tc.table_name, tc.constraint_type
ORDER BY tc.table_name, tc.constraint_type;

\echo '\n===== 5.2 Each constraint in action (every statement below is expected to FAIL, except DEFAULT) ====='
\echo '--- UNIQUE: duplicate username'
INSERT INTO users (id, username, email, password_hash, role, is_active)
VALUES (gen_random_uuid(), 'rahul_sharma', 'rahul2@example.in', 'x', 'CUSTOMER', TRUE);

\echo '--- FOREIGN KEY: profile for a user that does not exist'
INSERT INTO customers (id, user_id, full_name, kyc_status)
VALUES (gen_random_uuid(), '00000000-0000-4000-8000-000000000000', 'Ghost Customer', 'PENDING');

\echo '--- NOT NULL: customer without a name'
INSERT INTO customers (id, user_id, full_name, kyc_status)
SELECT gen_random_uuid(), id, NULL, 'PENDING' FROM users WHERE username = 'priya_investigator';

\echo '--- CHECK: non-INR account'
INSERT INTO accounts (id, customer_id, account_number, account_type, currency, cached_balance, status, version)
SELECT gen_random_uuid(), id, 'USD-SAV-00000001', 'SAVINGS', 'USD', 0.00, 'ACTIVE', 1
FROM customers WHERE full_name = 'Ananya Iyer';

\echo '--- CHECK: negative customer balance'
UPDATE accounts SET cached_balance = -500.00 WHERE account_number = 'INR-SAV-81A4C0E2';

\echo '--- CHECK: transfer to the same account'
INSERT INTO transfer_requests (id, idempotency_key, source_user_id, request_hash, source_account_id,
                               destination_account_id, amount, currency, status)
SELECT gen_random_uuid(), 'k-1', c.user_id, repeat('0', 64), a.id, a.id, 100.00, 'INR', 'PENDING'
FROM accounts a JOIN customers c ON c.id = a.customer_id WHERE a.account_number = 'INR-SAV-3BD2762D';

\echo '--- CHECK: invalid role'
INSERT INTO users (id, username, email, password_hash, role, is_active)
VALUES (gen_random_uuid(), 'mallory', 'm@example.in', 'x', 'SUPERUSER', TRUE);

\echo '--- DEFAULT: omitted columns are filled in'
INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id)
SELECT id, 'AUTH_LOGIN_SUCCESS', 'USER', id::text FROM users WHERE username = 'rahul_sharma'
RETURNING id, action, metadata_json, created_at IS NOT NULL AS created_at_defaulted;

\echo '\n===== 6.4 An unbalanced INSERT is refused at COMMIT (expected ERROR) ====='
BEGIN;
INSERT INTO ledger_transactions (id, transaction_type, description)
VALUES ('6f1d2c3b-0000-4000-8000-0000000000ff', 'INITIAL_DEPOSIT', 'Attempt to create money');
INSERT INTO ledger_entries (id, transaction_id, account_id, entry_type, amount, sequence_num)
SELECT gen_random_uuid(), '6f1d2c3b-0000-4000-8000-0000000000ff'::uuid, id, 'CREDIT', 99999.00, 1
FROM accounts WHERE account_number = 'INR-SAV-7A5F0C93';
COMMIT;

\echo '\n===== 6.5 UPDATE ====='
UPDATE customers SET kyc_status = 'VERIFIED', updated_at = now()
WHERE full_name IN ('Rahul Sharma', 'Ananya Iyer', 'Vikram Mehta', 'Sneha Kapoor');
UPDATE customers SET kyc_status = 'REJECTED', updated_at = now()
WHERE pan_number IS NULL;
UPDATE accounts SET status = 'FROZEN', version = version + 1, updated_at = now()
WHERE customer_id = (SELECT id FROM customers WHERE kyc_status = 'REJECTED');
UPDATE financial_products SET annual_yield_rate = 7.75 WHERE code = 'FD-36M-HY';
SELECT c.full_name, c.kyc_status, a.account_number, a.status
FROM customers c JOIN accounts a ON a.customer_id = c.id ORDER BY c.full_name, a.account_number;

\echo '\n===== 6.6 DELETE on reference data (allowed) ====='
INSERT INTO financial_products (id, name, code, product_type, annual_yield_rate, min_amount, term_months, is_active)
VALUES (gen_random_uuid(), 'Draft product - do not publish', 'DRAFT-TEST', 'MUTUAL_FUND', 0.00, 100.00, 1, FALSE);
DELETE FROM financial_products WHERE code = 'DRAFT-TEST' AND is_active = FALSE;
SELECT COUNT(*) AS products_after_delete FROM financial_products;

\echo '\n===== 6.6 DELETE / UPDATE on the ledger (expected ERRORs) ====='
DELETE FROM ledger_entries WHERE amount = 150000.00;
UPDATE ledger_entries SET amount = 1.00 WHERE amount = 150000.00;

\echo '\n===== 4.3 ALTER TABLE and DROP (KYC document register) ====='
CREATE TABLE kyc_documents (
    id            SERIAL       PRIMARY KEY,
    customer_id   UUID         NOT NULL REFERENCES customers(id),
    doc_type      VARCHAR(20)  NOT NULL,
    doc_number    VARCHAR(20)  NOT NULL,
    uploaded_on   DATE
);
ALTER TABLE kyc_documents ADD COLUMN verified_by VARCHAR(50);
ALTER TABLE kyc_documents ALTER COLUMN doc_number TYPE VARCHAR(30);
ALTER TABLE kyc_documents ALTER COLUMN uploaded_on SET DEFAULT CURRENT_DATE;
ALTER TABLE kyc_documents ADD CONSTRAINT chk_kyc_doc_type
      CHECK (doc_type IN ('PAN', 'AADHAAR', 'PASSPORT', 'VOTER_ID'));
ALTER TABLE kyc_documents ADD CONSTRAINT uq_kyc_doc UNIQUE (doc_type, doc_number);
ALTER TABLE kyc_documents RENAME COLUMN verified_by TO verified_by_staff;
\d kyc_documents
ALTER TABLE kyc_documents DROP COLUMN verified_by_staff;
ALTER TABLE kyc_documents DROP CONSTRAINT uq_kyc_doc;
DROP TABLE kyc_documents;

\echo '\n===== 7.1 Character functions ====='
SELECT UPPER(full_name)                         AS upper_name,
       LOWER(SPLIT_PART(full_name, ' ', 1))     AS first_lower,
       INITCAP('rahul sharma')                  AS initcap_demo,
       LENGTH(full_name)                        AS name_len,
       SUBSTR(pan_number, 1, 5)                 AS pan_alpha,
       CONCAT(LEFT(full_name, 1), '. ', SPLIT_PART(full_name, ' ', 2)) AS short_name,
       REPLACE(phone, '+91-', '0')              AS local_phone
FROM customers ORDER BY full_name;

\echo '\n===== 7.2 Character functions for masking account numbers ====='
SELECT account_number,
       LPAD(RIGHT(account_number, 4), LENGTH(account_number), 'X') AS masked,
       RPAD(account_type, 12, '.')                                  AS padded_type,
       TRIM(BOTH ' ' FROM '   INR   ')                              AS trimmed,
       POSITION('SAV' IN account_number)                            AS pos_sav
FROM accounts WHERE customer_id IS NOT NULL ORDER BY account_number;

\echo '\n===== 7.3 Number functions on product data ====='
SELECT code,
       annual_yield_rate,
       ROUND(min_amount * annual_yield_rate / 100, 2)                    AS yearly_interest,
       TRUNC(min_amount * annual_yield_rate / 1200, 1)                   AS monthly_interest_trunc,
       CEIL(term_months / 12.0)                                          AS years_ceil,
       FLOOR(term_months / 12.0)                                         AS years_floor,
       MOD(term_months, 12)                                              AS extra_months,
       ABS(annual_yield_rate - 7.00)                                     AS gap_from_7pct,
       POWER(1 + annual_yield_rate / 100, 2)::numeric(8,4)               AS growth_2y
FROM financial_products ORDER BY code;

\echo '\n===== 7.4 Date functions ====='
SELECT full_name,
       created_at::date                                  AS joined_on,
       TO_CHAR(created_at, 'DD-Mon-YYYY HH24:MI')        AS joined_fmt,
       EXTRACT(MONTH FROM created_at)                    AS join_month,
       DATE_PART('dow', created_at)                      AS day_of_week,
       AGE(DATE '2026-10-20', created_at::date)          AS customer_for,
       (created_at + INTERVAL '12 months')::date         AS fd_maturity_if_opened,
       DATE_TRUNC('month', created_at)::date             AS month_start
FROM customers ORDER BY created_at;

\echo '\n===== 7.5 Conversion and general functions ====='
SELECT account_number,
       TO_CHAR(cached_balance, 'FM99,99,99,990.00')          AS balance_text,
       CAST(cached_balance AS INTEGER)                        AS balance_int,
       cached_balance::text || ' INR'                         AS with_currency,
       COALESCE(c.phone, 'not provided')                      AS phone_nvl,
       NULLIF(a.status, 'ACTIVE')                             AS non_active_status,
       CASE a.account_type WHEN 'SAVINGS' THEN 'SB' WHEN 'CURRENT' THEN 'CA' ELSE 'SYS' END AS short_code
FROM accounts a LEFT JOIN customers c ON c.id = a.customer_id
ORDER BY a.account_number;

\echo '\n===== 8.1 Arithmetic operators ====='
SELECT code, min_amount, annual_yield_rate, term_months,
       ROUND(min_amount * annual_yield_rate / 100 * term_months / 12, 2)              AS simple_interest,
       ROUND(min_amount + min_amount * annual_yield_rate / 100 * term_months / 12, 2) AS maturity_value
FROM financial_products ORDER BY simple_interest DESC;

\echo '\n===== 8.1 Comparison and logical operators ====='
SELECT account_number, account_type, cached_balance, status
FROM accounts
WHERE account_type <> 'INTERNAL_CLEARING'
  AND (cached_balance >= 100000 OR account_type = 'CURRENT')
  AND NOT status = 'FROZEN'
ORDER BY cached_balance DESC;

\echo '\n===== 8.1 BETWEEN, IN, LIKE / ILIKE, NOT LIKE ====='
SELECT code, product_type, annual_yield_rate, term_months
FROM financial_products
WHERE annual_yield_rate BETWEEN 6.80 AND 7.20
  AND product_type IN ('FIXED_DEPOSIT', 'RECURRING_DEPOSIT', 'TREASURY_BILL')
  AND code LIKE '%-%-%';
SELECT full_name, email FROM customers c JOIN users u ON u.id = c.user_id
WHERE u.email ILIKE '%@EXAMPLE.IN' AND c.full_name NOT LIKE 'R%';

\echo '\n===== 8.1 IS NULL / IS NOT NULL ====='
SELECT full_name, phone, pan_number,
       CASE WHEN phone IS NULL OR pan_number IS NULL THEN 'Incomplete profile' ELSE 'Complete' END AS profile
FROM customers WHERE phone IS NULL OR pan_number IS NULL;

\echo '\n===== 8.1 Set operators (UNION, EXCEPT, INTERSECT) ====='
SELECT username, 'customer' AS kind FROM users WHERE id IN (SELECT user_id FROM customers)
UNION
SELECT username, 'staff/admin' FROM users WHERE role IN ('STAFF', 'ADMIN')
ORDER BY kind, username;

SELECT a.account_number FROM ledger_entries e JOIN accounts a ON a.id = e.account_id
WHERE e.entry_type = 'CREDIT'
EXCEPT
SELECT account_number FROM accounts WHERE status = 'FROZEN'
ORDER BY 1;

SELECT a.account_number FROM accounts a WHERE a.id IN (
  SELECT account_id FROM ledger_entries WHERE entry_type = 'CREDIT'
  INTERSECT
  SELECT id FROM accounts WHERE account_type = 'SAVINGS')
ORDER BY 1;

\echo '\n===== 8.2 COUNT, COUNT(DISTINCT), SUM, AVG, MIN, MAX ====='
SELECT COUNT(*)                     AS total_accounts,
       COUNT(customer_id)           AS customer_accounts,
       COUNT(DISTINCT customer_id)  AS distinct_customers,
       SUM(cached_balance) FILTER (WHERE account_type <> 'INTERNAL_CLEARING') AS customer_liabilities,
       ROUND(AVG(cached_balance) FILTER (WHERE account_type <> 'INTERNAL_CLEARING'), 2) AS avg_balance,
       MIN(cached_balance) FILTER (WHERE account_type <> 'INTERNAL_CLEARING') AS min_balance,
       MAX(cached_balance)          AS max_balance
FROM accounts;

\echo '\n===== 8.2 GROUP BY on two columns ====='
SELECT account_type, status, COUNT(*) AS accounts, SUM(cached_balance) AS total_balance
FROM accounts
GROUP BY account_type, status
ORDER BY account_type, status;

\echo '\n===== 8.2 HAVING — customers holding more than 1,00,000 ====='
SELECT c.full_name, COUNT(a.id) AS num_accounts, SUM(a.cached_balance) AS net_worth
FROM customers c JOIN accounts a ON a.customer_id = c.id
GROUP BY c.full_name
HAVING SUM(a.cached_balance) > 100000
ORDER BY net_worth DESC;

\echo '\n===== 8.2 GROUP BY proving double entry ====='
SELECT t.description,
       COUNT(e.id)                                                    AS legs,
       SUM(e.amount) FILTER (WHERE e.entry_type = 'DEBIT')            AS total_debit,
       SUM(e.amount) FILTER (WHERE e.entry_type = 'CREDIT')           AS total_credit,
       SUM(CASE WHEN e.entry_type = 'DEBIT' THEN e.amount ELSE -e.amount END) AS difference
FROM ledger_transactions t JOIN ledger_entries e ON e.transaction_id = t.id
GROUP BY t.id, t.description
ORDER BY t.description;

\echo '\n===== 8.2 Aggregates per product type with STRING_AGG ====='
SELECT product_type, COUNT(*) AS products, MIN(annual_yield_rate) AS min_rate,
       MAX(annual_yield_rate) AS max_rate, ROUND(AVG(annual_yield_rate), 2) AS avg_rate,
       STRING_AGG(code, ', ' ORDER BY code) AS codes
FROM financial_products
GROUP BY product_type
ORDER BY avg_rate DESC;
