"""Stored procedures for every money movement, plus reconciliation and statement views.

Every procedure locks the accounts it touches in ascending id order (canonical lock order),
so two opposite transfers can never deadlock. The lock is FOR NO KEY UPDATE: it serialises
money movements on an account but does not block the FOR KEY SHARE locks that foreign-key
checks take (FOR UPDATE would, and a FAILED-transfer insert could then deadlock a posting). Business-rule failures are raised with
project-specific SQLSTATE codes that the API maps to HTTP errors:

    FLAMT invalid amount         FLSAM same source/destination   FLNFD not found
    FLOWN caller not the owner   FLSTS account not ACTIVE        FLNSF insufficient funds
    FLINT internal account       FLPRD product unavailable       FLMIN below product minimum
    FLREV transfer not POSTED    FLROL role not permitted

Revision ID: d9e4a1b7c6f3
Revises: c5d2f8a9e3b2
Create Date: 2026-09-02
"""
from alembic import op

revision = "d9e4a1b7c6f3"
down_revision = "c5d2f8a9e3b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_post_deposit(
            p_account_id   UUID,
            p_amount       NUMERIC(15,2),
            p_description  VARCHAR(255)
        ) RETURNS UUID
        LANGUAGE plpgsql AS $$
        DECLARE
            v_clearing  accounts%ROWTYPE;
            v_target    accounts%ROWTYPE;
            v_txn_id    UUID := gen_random_uuid();
        BEGIN
            IF p_amount IS NULL OR p_amount <= 0 THEN
                RAISE EXCEPTION 'Deposit amount must be positive' USING ERRCODE = 'FLAMT';
            END IF;

            SELECT * INTO v_clearing FROM accounts WHERE account_number = 'INR-SYS-CLEARING';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Clearing account INR-SYS-CLEARING is missing' USING ERRCODE = 'FLNFD';
            END IF;

            PERFORM 1 FROM accounts WHERE id IN (v_clearing.id, p_account_id) ORDER BY id FOR NO KEY UPDATE;

            SELECT * INTO v_target FROM accounts WHERE id = p_account_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Account % not found', p_account_id USING ERRCODE = 'FLNFD';
            END IF;
            IF v_target.account_type NOT IN ('SAVINGS', 'CURRENT') THEN
                RAISE EXCEPTION 'Deposits are only accepted into savings or current accounts' USING ERRCODE = 'FLINT';
            END IF;
            IF v_target.status <> 'ACTIVE' THEN
                RAISE EXCEPTION 'Account % is %', v_target.account_number, v_target.status USING ERRCODE = 'FLSTS';
            END IF;

            INSERT INTO ledger_transactions (id, transaction_type, description)
            VALUES (v_txn_id, 'INITIAL_DEPOSIT', COALESCE(p_description, 'Deposit ' || v_target.account_number));

            INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num) VALUES
                (v_txn_id, v_clearing.id, 'DEBIT',  p_amount, 1),
                (v_txn_id, v_target.id,   'CREDIT', p_amount, 2);

            UPDATE accounts SET cached_balance = cached_balance - p_amount, version = version + 1, updated_at = now()
             WHERE id = v_clearing.id;
            UPDATE accounts SET cached_balance = cached_balance + p_amount, version = version + 1, updated_at = now()
             WHERE id = v_target.id;

            RETURN v_txn_id;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_transfer_funds(
            p_source_user_id          UUID,
            p_idempotency_key         VARCHAR(64),
            p_request_hash            VARCHAR(64),
            p_source_account_id       UUID,
            p_destination_account_id  UUID,
            p_amount                  NUMERIC(15,2),
            p_description             VARCHAR(255)
        ) RETURNS UUID
        LANGUAGE plpgsql AS $$
        DECLARE
            v_src          accounts%ROWTYPE;
            v_dst          accounts%ROWTYPE;
            v_owner        UUID;
            v_transfer_id  UUID := gen_random_uuid();
            v_txn_id       UUID := gen_random_uuid();
        BEGIN
            IF p_amount IS NULL OR p_amount <= 0 THEN
                RAISE EXCEPTION 'Transfer amount must be positive' USING ERRCODE = 'FLAMT';
            END IF;
            IF p_source_account_id = p_destination_account_id THEN
                RAISE EXCEPTION 'Source and destination accounts must differ' USING ERRCODE = 'FLSAM';
            END IF;

            -- Canonical lock order: ascending id, whichever account is the source.
            PERFORM 1 FROM accounts
             WHERE id IN (p_source_account_id, p_destination_account_id)
             ORDER BY id
               FOR NO KEY UPDATE;

            SELECT * INTO v_src FROM accounts WHERE id = p_source_account_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Source account not found' USING ERRCODE = 'FLNFD';
            END IF;
            SELECT * INTO v_dst FROM accounts WHERE id = p_destination_account_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Destination account not found' USING ERRCODE = 'FLNFD';
            END IF;

            SELECT c.user_id INTO v_owner FROM customers c WHERE c.id = v_src.customer_id;
            IF v_owner IS DISTINCT FROM p_source_user_id THEN
                RAISE EXCEPTION 'You can only transfer from your own accounts' USING ERRCODE = 'FLOWN';
            END IF;
            IF v_src.account_type NOT IN ('SAVINGS', 'CURRENT') OR v_dst.account_type NOT IN ('SAVINGS', 'CURRENT') THEN
                RAISE EXCEPTION 'Transfers are only allowed between savings and current accounts' USING ERRCODE = 'FLINT';
            END IF;
            IF v_src.status <> 'ACTIVE' THEN
                RAISE EXCEPTION 'Source account % is %', v_src.account_number, v_src.status USING ERRCODE = 'FLSTS';
            END IF;
            IF v_dst.status <> 'ACTIVE' THEN
                RAISE EXCEPTION 'Destination account % is %', v_dst.account_number, v_dst.status USING ERRCODE = 'FLSTS';
            END IF;
            IF v_src.cached_balance < p_amount THEN
                RAISE EXCEPTION 'Insufficient funds: available %, requested %', v_src.cached_balance, p_amount
                    USING ERRCODE = 'FLNSF';
            END IF;

            INSERT INTO transfer_requests (id, idempotency_key, source_user_id, request_hash, source_account_id,
                                           destination_account_id, amount, currency, status, posted_at)
            VALUES (v_transfer_id, p_idempotency_key, p_source_user_id, p_request_hash, v_src.id,
                    v_dst.id, p_amount, 'INR', 'POSTED', now());

            INSERT INTO ledger_transactions (id, transfer_request_id, transaction_type, description)
            VALUES (v_txn_id, v_transfer_id, 'CUSTOMER_TRANSFER',
                    COALESCE(NULLIF(p_description, ''), 'Transfer ' || v_src.account_number || ' -> ' || v_dst.account_number));

            INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num) VALUES
                (v_txn_id, v_src.id, 'DEBIT',  p_amount, 1),
                (v_txn_id, v_dst.id, 'CREDIT', p_amount, 2);

            UPDATE accounts SET cached_balance = cached_balance - p_amount, version = version + 1, updated_at = now()
             WHERE id = v_src.id;
            UPDATE accounts SET cached_balance = cached_balance + p_amount, version = version + 1, updated_at = now()
             WHERE id = v_dst.id;

            -- Money-flow graph edge for the graph detector.
            INSERT INTO payee_edges (source_account_id, destination_account_id, transfer_count, total_amount)
            VALUES (v_src.id, v_dst.id, 1, p_amount)
            ON CONFLICT (source_account_id, destination_account_id) DO UPDATE
               SET transfer_count = payee_edges.transfer_count + 1,
                   total_amount   = payee_edges.total_amount + EXCLUDED.total_amount,
                   last_seen_at   = now();

            RETURN v_transfer_id;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_reverse_transfer(
            p_transfer_id    UUID,
            p_admin_user_id  UUID,
            p_reason         TEXT
        ) RETURNS UUID
        LANGUAGE plpgsql AS $$
        DECLARE
            v_role      VARCHAR(20);
            v_tr        transfer_requests%ROWTYPE;
            v_src       accounts%ROWTYPE;
            v_dst       accounts%ROWTYPE;
            v_txn_id    UUID := gen_random_uuid();
        BEGIN
            SELECT role INTO v_role FROM users WHERE id = p_admin_user_id AND is_active;
            IF v_role IS DISTINCT FROM 'ADMIN' THEN
                RAISE EXCEPTION 'Only an admin may post a correction reversal' USING ERRCODE = 'FLROL';
            END IF;

            SELECT * INTO v_tr FROM transfer_requests WHERE id = p_transfer_id FOR NO KEY UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Transfer % not found', p_transfer_id USING ERRCODE = 'FLNFD';
            END IF;
            IF v_tr.status <> 'POSTED' THEN
                RAISE EXCEPTION 'Only POSTED transfers can be reversed (status is %)', v_tr.status USING ERRCODE = 'FLREV';
            END IF;

            PERFORM 1 FROM accounts
             WHERE id IN (v_tr.source_account_id, v_tr.destination_account_id)
             ORDER BY id
               FOR NO KEY UPDATE;
            SELECT * INTO v_src FROM accounts WHERE id = v_tr.source_account_id;
            SELECT * INTO v_dst FROM accounts WHERE id = v_tr.destination_account_id;

            IF v_src.status = 'CLOSED' OR v_dst.status = 'CLOSED' THEN
                RAISE EXCEPTION 'Cannot reverse a transfer involving a closed account' USING ERRCODE = 'FLSTS';
            END IF;
            IF v_dst.cached_balance < v_tr.amount THEN
                RAISE EXCEPTION 'Destination account % holds only %; cannot return %',
                    v_dst.account_number, v_dst.cached_balance, v_tr.amount USING ERRCODE = 'FLNSF';
            END IF;

            -- The description names the reversed transfer; its status becomes REVERSED below.
            INSERT INTO ledger_transactions (id, transaction_type, description)
            VALUES (v_txn_id, 'CORRECTION_REVERSAL',
                    left('Reversal of transfer ' || p_transfer_id || ': ' || COALESCE(p_reason, ''), 255));

            INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num) VALUES
                (v_txn_id, v_dst.id, 'DEBIT',  v_tr.amount, 1),
                (v_txn_id, v_src.id, 'CREDIT', v_tr.amount, 2);

            UPDATE accounts SET cached_balance = cached_balance - v_tr.amount, version = version + 1, updated_at = now()
             WHERE id = v_dst.id;
            UPDATE accounts SET cached_balance = cached_balance + v_tr.amount, version = version + 1, updated_at = now()
             WHERE id = v_src.id;

            UPDATE transfer_requests SET status = 'REVERSED' WHERE id = p_transfer_id;

            RETURN v_txn_id;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION sp_purchase_investment(
            p_user_id             UUID,
            p_funding_account_id  UUID,
            p_product_id          UUID,
            p_amount              NUMERIC(15,2)
        ) RETURNS UUID
        LANGUAGE plpgsql AS $$
        DECLARE
            v_customer_id  UUID;
            v_product      financial_products%ROWTYPE;
            v_fund         accounts%ROWTYPE;
            v_inv_acc_id   UUID;
            v_txn_id       UUID := gen_random_uuid();
            v_inv_id       UUID := gen_random_uuid();
        BEGIN
            IF p_amount IS NULL OR p_amount <= 0 THEN
                RAISE EXCEPTION 'Investment amount must be positive' USING ERRCODE = 'FLAMT';
            END IF;

            SELECT id INTO v_customer_id FROM customers WHERE user_id = p_user_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Only customers can invest' USING ERRCODE = 'FLOWN';
            END IF;

            SELECT * INTO v_product FROM financial_products WHERE id = p_product_id;
            IF NOT FOUND OR NOT v_product.is_active THEN
                RAISE EXCEPTION 'Product is not available' USING ERRCODE = 'FLPRD';
            END IF;
            IF p_amount < v_product.min_amount THEN
                RAISE EXCEPTION 'Minimum investment for % is %', v_product.code, v_product.min_amount USING ERRCODE = 'FLMIN';
            END IF;

            -- The customer's investment account is opened on first purchase.
            SELECT id INTO v_inv_acc_id FROM accounts
             WHERE customer_id = v_customer_id AND account_type = 'INVESTMENT' AND status = 'ACTIVE'
             ORDER BY created_at LIMIT 1;
            IF v_inv_acc_id IS NULL THEN
                INSERT INTO accounts (customer_id, account_number, account_type)
                VALUES (v_customer_id,
                        'INR-INV-' || upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8)),
                        'INVESTMENT')
                RETURNING id INTO v_inv_acc_id;
            END IF;

            PERFORM 1 FROM accounts WHERE id IN (p_funding_account_id, v_inv_acc_id) ORDER BY id FOR NO KEY UPDATE;

            SELECT * INTO v_fund FROM accounts WHERE id = p_funding_account_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Funding account not found' USING ERRCODE = 'FLNFD';
            END IF;
            IF v_fund.customer_id IS DISTINCT FROM v_customer_id THEN
                RAISE EXCEPTION 'You can only invest from your own accounts' USING ERRCODE = 'FLOWN';
            END IF;
            IF v_fund.account_type NOT IN ('SAVINGS', 'CURRENT') THEN
                RAISE EXCEPTION 'Investments must be funded from a savings or current account' USING ERRCODE = 'FLINT';
            END IF;
            IF v_fund.status <> 'ACTIVE' THEN
                RAISE EXCEPTION 'Funding account % is %', v_fund.account_number, v_fund.status USING ERRCODE = 'FLSTS';
            END IF;
            IF v_fund.cached_balance < p_amount THEN
                RAISE EXCEPTION 'Insufficient funds: available %, requested %', v_fund.cached_balance, p_amount
                    USING ERRCODE = 'FLNSF';
            END IF;

            INSERT INTO ledger_transactions (id, transaction_type, description)
            VALUES (v_txn_id, 'INVESTMENT_PURCHASE', 'Investment in ' || v_product.code);

            INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num) VALUES
                (v_txn_id, v_fund.id,     'DEBIT',  p_amount, 1),
                (v_txn_id, v_inv_acc_id,  'CREDIT', p_amount, 2);

            UPDATE accounts SET cached_balance = cached_balance - p_amount, version = version + 1, updated_at = now()
             WHERE id = v_fund.id;
            UPDATE accounts SET cached_balance = cached_balance + p_amount, version = version + 1, updated_at = now()
             WHERE id = v_inv_acc_id;

            INSERT INTO investments (id, customer_id, account_id, product_id, investment_account_id, ledger_transaction_id,
                                     principal, annual_yield_rate, start_date, maturity_date, expected_maturity_value)
            VALUES (v_inv_id, v_customer_id, v_fund.id, v_product.id, v_inv_acc_id, v_txn_id,
                    p_amount, v_product.annual_yield_rate, CURRENT_DATE,
                    (CURRENT_DATE + make_interval(months => v_product.term_months))::date,
                    round(p_amount + p_amount * v_product.annual_yield_rate / 100 * v_product.term_months / 12, 2));

            RETURN v_inv_id;
        END;
        $$;
        """
    )

    op.execute(
        """
        -- BR15: cached_balance must equal SUM(credits) - SUM(debits).
        CREATE VIEW v_account_reconciliation AS
        SELECT a.id                AS account_id,
               a.account_number,
               a.account_type,
               a.status,
               a.cached_balance,
               COALESCE(SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END), 0)::NUMERIC(15,2)
                                   AS ledger_balance,
               (a.cached_balance
                - COALESCE(SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END), 0))::NUMERIC(15,2)
                                   AS discrepancy,
               COUNT(e.id)         AS leg_count
          FROM accounts a
          LEFT JOIN ledger_entries e ON e.account_id = a.id
         GROUP BY a.id;

        -- Statement lines with a running balance (window function) and the counterparty account(s).
        CREATE VIEW v_account_statement AS
        SELECT e.account_id,
               e.id               AS entry_id,
               e.transaction_id,
               t.transaction_type,
               t.description,
               t.transfer_request_id,
               e.entry_type,
               e.amount,
               e.sequence_num,
               e.created_at,
               SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END)
                   OVER (PARTITION BY e.account_id ORDER BY e.created_at, e.sequence_num, e.id
                         ROWS UNBOUNDED PRECEDING)::NUMERIC(15,2) AS running_balance,
               (SELECT string_agg(a2.account_number, ', ' ORDER BY a2.account_number)
                  FROM ledger_entries e2 JOIN accounts a2 ON a2.id = e2.account_id
                 WHERE e2.transaction_id = e.transaction_id AND e2.entry_type <> e.entry_type) AS counterparty
          FROM ledger_entries e
          JOIN ledger_transactions t ON t.id = e.transaction_id;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_account_statement")
    op.execute("DROP VIEW IF EXISTS v_account_reconciliation")
    op.execute("DROP FUNCTION IF EXISTS sp_purchase_investment(UUID, UUID, UUID, NUMERIC)")
    op.execute("DROP FUNCTION IF EXISTS sp_reverse_transfer(UUID, UUID, TEXT)")
    op.execute("DROP FUNCTION IF EXISTS sp_transfer_funds(UUID, VARCHAR, VARCHAR, UUID, UUID, NUMERIC, VARCHAR)")
    op.execute("DROP FUNCTION IF EXISTS sp_post_deposit(UUID, NUMERIC, VARCHAR)")
