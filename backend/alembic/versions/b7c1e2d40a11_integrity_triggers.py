"""Integrity triggers: append-only ledger/audit, guarded TRUNCATE, deferred double-entry check.

Revision ID: b7c1e2d40a11
Revises: aa388336f576
Create Date: 2026-08-06
"""
from alembic import op

revision = "b7c1e2d40a11"
down_revision = "aa388336f576"
branch_labels = None
depends_on = None

APPEND_ONLY_TABLES = ("ledger_entries", "ledger_transactions", "audit_logs")


def upgrade() -> None:
    # BR9: committed rows in the ledger and the audit trail can never change.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_record_modification() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Table % is strictly append-only; updates and deletes are prohibited', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    # Row-level triggers do not fire for TRUNCATE, so a statement-level guard is needed.
    # Test and benchmark resets opt in with: SET LOCAL finledger.allow_truncate = 'on'.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_append_only_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('finledger.allow_truncate', true) = 'on' THEN
                RETURN NULL;
            END IF;

            RAISE EXCEPTION 'Table % is strictly append-only; TRUNCATE is prohibited', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$;
        """
    )
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_immutable_{table}
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION prevent_record_modification();
            CREATE TRIGGER trg_no_truncate_{table}
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION prevent_append_only_truncate();
            """
        )

    # BR8: in every ledger transaction SUM(debits) = SUM(credits). Checked at COMMIT so that the
    # legs of one posting may be inserted one after the other.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION verify_transaction_balance() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_delta NUMERIC(17,2);
        BEGIN
            SELECT COALESCE(SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE -amount END), 0)
              INTO v_delta
              FROM ledger_entries
             WHERE transaction_id = NEW.transaction_id;

            IF v_delta <> 0 THEN
                RAISE EXCEPTION 'Ledger transaction % is unbalanced: debit minus credit delta is %',
                    NEW.transaction_id, v_delta
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_verify_ledger_balance
            AFTER INSERT ON ledger_entries
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION verify_transaction_balance();
        """
    )
    # Total participation: a ledger header must own at least two legs by COMMIT.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION verify_transaction_has_legs() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            v_legs INTEGER;
        BEGIN
            SELECT COUNT(*) INTO v_legs FROM ledger_entries WHERE transaction_id = NEW.id;
            -- One positive leg can never balance, so the balance trigger already covers v_legs = 1.
            IF v_legs = 0 THEN
                RAISE EXCEPTION 'Ledger transaction % has no legs (a posting needs at least two legs)', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE CONSTRAINT TRIGGER trg_verify_ledger_legs
            AFTER INSERT ON ledger_transactions
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION verify_transaction_has_legs();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_verify_ledger_legs ON ledger_transactions")
    op.execute("DROP TRIGGER IF EXISTS trg_verify_ledger_balance ON ledger_entries")
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_immutable_{table} ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS trg_no_truncate_{table} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS verify_transaction_has_legs()")
    op.execute("DROP FUNCTION IF EXISTS verify_transaction_balance()")
    op.execute("DROP FUNCTION IF EXISTS prevent_append_only_truncate()")
    op.execute("DROP FUNCTION IF EXISTS prevent_record_modification()")
