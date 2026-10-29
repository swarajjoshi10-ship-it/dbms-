"""Supporting tables: investments, disputes, case events, payees, notes, graph, Fraud Lab.

Revision ID: c5d2f8a9e3b2
Revises: b7c1e2d40a11
Create Date: 2026-08-19
"""
from alembic import op

revision = "c5d2f8a9e3b2"
down_revision = "b7c1e2d40a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE investments (
            id                       UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id              UUID          NOT NULL REFERENCES customers(id)          ON DELETE RESTRICT,
            account_id               UUID          NOT NULL REFERENCES accounts(id)           ON DELETE RESTRICT,
            product_id               UUID          NOT NULL REFERENCES financial_products(id) ON DELETE RESTRICT,
            investment_account_id    UUID          NOT NULL REFERENCES accounts(id)           ON DELETE RESTRICT,
            ledger_transaction_id    UUID          NOT NULL UNIQUE REFERENCES ledger_transactions(id) ON DELETE RESTRICT,
            principal                NUMERIC(15,2) NOT NULL,
            annual_yield_rate        NUMERIC(5,2)  NOT NULL,
            start_date               DATE          NOT NULL DEFAULT CURRENT_DATE,
            maturity_date            DATE          NOT NULL,
            expected_maturity_value  NUMERIC(15,2) NOT NULL,
            status                   VARCHAR(20)   NOT NULL DEFAULT 'ACTIVE',
            created_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT chk_investments_principal_positive CHECK (principal > 0.00),
            CONSTRAINT chk_investments_status_valid CHECK (status IN ('ACTIVE','MATURED','CLOSED')),
            CONSTRAINT chk_investments_dates CHECK (maturity_date > start_date)
        );
        CREATE INDEX ix_investments_customer_id ON investments (customer_id);

        CREATE TABLE disputes (
            id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id          UUID         NOT NULL REFERENCES customers(id)         ON DELETE RESTRICT,
            transfer_request_id  UUID         NOT NULL REFERENCES transfer_requests(id) ON DELETE RESTRICT,
            reason               VARCHAR(30)  NOT NULL,
            description          TEXT         NOT NULL,
            status               VARCHAR(20)  NOT NULL DEFAULT 'OPEN',
            assigned_staff_id    UUID         REFERENCES users(id) ON DELETE RESTRICT,
            resolution_notes     TEXT,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            resolved_at          TIMESTAMPTZ,
            CONSTRAINT chk_disputes_reason_valid CHECK (reason IN
                ('UNAUTHORIZED','WRONG_RECIPIENT','WRONG_AMOUNT','SCAM','OTHER')),
            CONSTRAINT chk_disputes_status_valid CHECK (status IN
                ('OPEN','INVESTIGATING','RESOLVED_UPHELD','RESOLVED_REJECTED')),
            CONSTRAINT chk_disputes_resolution CHECK
                (status NOT LIKE 'RESOLVED%' OR (resolution_notes IS NOT NULL AND resolved_at IS NOT NULL))
        );
        -- At most one open case per transfer.
        CREATE UNIQUE INDEX uq_disputes_open_per_transfer ON disputes (transfer_request_id)
            WHERE status IN ('OPEN','INVESTIGATING');

        CREATE TABLE case_events (
            id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            dispute_id     UUID         NOT NULL REFERENCES disputes(id) ON DELETE RESTRICT,
            actor_user_id  UUID         REFERENCES users(id) ON DELETE RESTRICT,
            event_type     VARCHAR(30)  NOT NULL,
            message        TEXT         NOT NULL,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT chk_case_events_type_valid CHECK (event_type IN
                ('OPENED','ASSIGNED','COMMENT','STATUS_CHANGE','RESOLVED'))
        );
        CREATE INDEX ix_case_events_dispute ON case_events (dispute_id, created_at);

        CREATE TABLE saved_payees (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id       UUID         NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            payee_account_id  UUID         NOT NULL REFERENCES accounts(id)  ON DELETE CASCADE,
            nickname          VARCHAR(50)  NOT NULL,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT uq_saved_payees_customer_account UNIQUE (customer_id, payee_account_id)
        );

        CREATE TABLE investigation_notes (
            id                   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            fraud_prediction_id  UUID         NOT NULL REFERENCES fraud_predictions(id) ON DELETE RESTRICT,
            author_user_id       UUID         NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            note                 TEXT         NOT NULL,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT chk_investigation_note_not_blank CHECK (length(trim(note)) > 0)
        );

        CREATE TABLE payee_edges (
            id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            source_account_id       UUID          NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            destination_account_id  UUID          NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            transfer_count          INTEGER       NOT NULL DEFAULT 0,
            total_amount            NUMERIC(15,2) NOT NULL DEFAULT 0.00,
            first_seen_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
            last_seen_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT uq_payee_edges_pair UNIQUE (source_account_id, destination_account_id),
            CONSTRAINT chk_payee_edges_distinct CHECK (source_account_id <> destination_account_id),
            CONSTRAINT chk_payee_edges_count CHECK (transfer_count >= 0)
        );

        CREATE TABLE graph_findings (
            id                    UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            finding_type          VARCHAR(30)   NOT NULL,
            primary_account_id    UUID          NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
            involved_account_ids  JSONB         NOT NULL DEFAULT '[]',
            total_amount          NUMERIC(15,2) NOT NULL DEFAULT 0.00,
            severity              VARCHAR(10)   NOT NULL,
            details               JSONB         NOT NULL DEFAULT '{}',
            status                VARCHAR(20)   NOT NULL DEFAULT 'OPEN',
            created_at            TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT chk_graph_finding_type CHECK (finding_type IN ('CYCLE','FAN_IN','RAPID_PASS_THROUGH')),
            CONSTRAINT chk_graph_finding_severity CHECK (severity IN ('LOW','MEDIUM','HIGH')),
            CONSTRAINT chk_graph_finding_status CHECK (status IN ('OPEN','DISMISSED','CONFIRMED'))
        );

        CREATE TABLE simulation_runs (
            id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
            run_by_user_id  UUID          NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            model_version   VARCHAR(30)   NOT NULL,
            scenario        JSONB         NOT NULL DEFAULT '{}',
            n_samples       INTEGER       NOT NULL,
            accuracy        NUMERIC(5,4)  NOT NULL,
            precision_score NUMERIC(5,4)  NOT NULL,
            recall_score    NUMERIC(5,4)  NOT NULL,
            f1_score        NUMERIC(5,4)  NOT NULL,
            confusion       JSONB         NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            CONSTRAINT chk_simulation_samples CHECK (n_samples > 0)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS simulation_runs, graph_findings, payee_edges, investigation_notes,
            saved_payees, case_events, disputes, investments CASCADE;
        """
    )
