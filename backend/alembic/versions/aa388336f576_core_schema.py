"""Core schema: users, customers, accounts, products, transfers, ledger, audit, fraud.

Revision ID: aa388336f576
Revises:
Create Date: 2026-08-04
"""
from alembic import op

revision = "aa388336f576"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.execute(
        """
        CREATE TABLE users (
            id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            username       VARCHAR(50)  NOT NULL,
            email          VARCHAR(255) NOT NULL,
            password_hash  VARCHAR(255) NOT NULL,
            role           VARCHAR(20)  NOT NULL,
            is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT chk_users_role_valid CHECK (role IN ('CUSTOMER', 'STAFF', 'ADMIN'))
        );
        CREATE UNIQUE INDEX ix_users_username ON users (username);
        CREATE UNIQUE INDEX ix_users_email ON users (email);

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
            customer_id     UUID          REFERENCES customers(id) ON DELETE RESTRICT,
            account_number  VARCHAR(32)   NOT NULL,
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
        CREATE UNIQUE INDEX ix_accounts_account_number ON accounts (account_number);
        CREATE INDEX ix_accounts_customer_id ON accounts (customer_id);

        CREATE TABLE financial_products (
            id                 UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            name               VARCHAR(100)  NOT NULL,
            code               VARCHAR(32)   NOT NULL,
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
        CREATE UNIQUE INDEX ix_financial_products_code ON financial_products (code);

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
        CREATE INDEX ix_ledger_entries_transaction_id ON ledger_entries (transaction_id);

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
        CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at DESC);

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

        -- Performance indexes (optimisation phase)
        CREATE INDEX idx_ledger_entries_account_created_seq
            ON ledger_entries (account_id, created_at DESC, sequence_num DESC);
        CREATE INDEX idx_transfers_status_created ON transfer_requests (status, created_at DESC);
        CREATE INDEX idx_fraud_pending_queue ON fraud_predictions (risk_score DESC, created_at DESC)
            WHERE review_status = 'PENDING';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS fraud_predictions, audit_logs, ledger_entries, ledger_transactions,
            transfer_requests, financial_products, accounts, customers, users CASCADE;
        """
    )
