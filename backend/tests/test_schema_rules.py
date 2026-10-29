"""The database enforces the financial rules even when application code is bypassed."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine
from tests.conftest import Customer, scalar


def run(sql: str, **params):
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def error_of(sql: str, **params) -> str:
    with pytest.raises(DBAPIError) as exc:
        run(sql, **params)
    return str(exc.value.orig)


def test_unbalanced_posting_is_refused_at_commit(client):
    c = Customer(client, "rahul")
    txn = uuid.uuid4()
    with pytest.raises(DBAPIError) as exc:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO ledger_transactions (id, transaction_type, description) "
                              "VALUES (:t, 'INITIAL_DEPOSIT', 'Create money')"), {"t": txn})
            # Both statements succeed on their own; the deferred trigger refuses the COMMIT.
            conn.execute(text("INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num) "
                              "VALUES (:t, :a, 'CREDIT', 99999.00, 1)"), {"t": txn, "a": c.account_id})
    assert "is unbalanced" in str(exc.value.orig)
    assert scalar("SELECT COUNT(*) FROM ledger_transactions WHERE id = :t", t=txn) == 0


def test_ledger_header_needs_at_least_two_legs():
    assert "at least two legs" in error_of(
        "INSERT INTO ledger_transactions (transaction_type, description) VALUES ('INITIAL_DEPOSIT', 'empty')"
    )


def test_balanced_manual_posting_commits(client):
    c = Customer(client, "rahul")
    run(
        """
        WITH txn AS (INSERT INTO ledger_transactions (transaction_type, description)
                     VALUES ('INITIAL_DEPOSIT', 'manual') RETURNING id)
        INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num)
        SELECT txn.id, a.id, leg.t, 500.00, leg.s FROM txn
        CROSS JOIN (VALUES ('INR-SYS-CLEARING', 'DEBIT', 1), (:n, 'CREDIT', 2)) AS leg(n, t, s)
        JOIN accounts a ON a.account_number = leg.n
        """,
        n=c.account_number,
    )
    assert scalar("SELECT COUNT(*) FROM ledger_entries") == 2


@pytest.mark.parametrize("statement", [
    "UPDATE ledger_entries SET amount = 1.00",
    "DELETE FROM ledger_entries",
    "UPDATE ledger_transactions SET description = 'edited'",
    "DELETE FROM audit_logs",
    "UPDATE audit_logs SET action = 'X'",
])
def test_ledger_and_audit_are_append_only(client, statement):
    c = Customer(client, "rahul", 1000)  # creates ledger rows and audit rows
    assert c.balance() == 1000
    assert "append-only" in error_of(statement)


@pytest.mark.parametrize("table", ["ledger_entries", "ledger_transactions", "audit_logs"])
def test_truncate_is_refused_without_opt_in(table):
    assert "TRUNCATE is prohibited" in error_of(f"TRUNCATE TABLE {table} CASCADE")


def test_customer_balance_cannot_go_negative(client):
    c = Customer(client, "rahul")
    assert "chk_accounts_non_negative_balance" in error_of(
        "UPDATE accounts SET cached_balance = -500.00 WHERE id = :a", a=c.account_id
    )


def test_clearing_account_may_be_negative(client):
    Customer(client, "rahul", 2500)
    assert scalar("SELECT cached_balance FROM accounts WHERE account_number = 'INR-SYS-CLEARING'") == -2500


def test_only_inr_accounts(client):
    c = Customer(client, "rahul")
    assert "chk_accounts_currency_inr" in error_of(
        """INSERT INTO accounts (customer_id, account_number, account_type, currency)
           SELECT customer_id, 'USD-SAV-00000001', 'SAVINGS', 'USD' FROM accounts WHERE id = :a""",
        a=c.account_id,
    )


def test_transfer_to_same_account_violates_check(client):
    c = Customer(client, "rahul")
    assert "chk_transfers_distinct_accounts" in error_of(
        """INSERT INTO transfer_requests (idempotency_key, source_user_id, request_hash, source_account_id,
                                          destination_account_id, amount, status)
           VALUES ('k-1', :u, repeat('0', 64), :a, :a, 100.00, 'PENDING')""",
        u=c.user_id, a=c.account_id,
    )


def test_invalid_role_is_rejected():
    assert "chk_users_role_valid" in error_of(
        "INSERT INTO users (username, email, password_hash, role) VALUES ('mallory', 'm@example.in', 'x', 'SUPERUSER')"
    )


def test_unique_username(client):
    Customer(client, "rahul")
    assert "ix_users_username" in error_of(
        "INSERT INTO users (username, email, password_hash, role) VALUES ('rahul', 'r2@example.in', 'x', 'CUSTOMER')"
    )


def test_audit_defaults_are_filled():
    run("INSERT INTO audit_logs (action, entity_type, entity_id) VALUES ('TEST', 'TEST', '1')")
    assert scalar("SELECT metadata_json::text FROM audit_logs WHERE action = 'TEST'") == "{}"
