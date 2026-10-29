import threading
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import Customer, scalar


def test_transfer_moves_money_as_balanced_legs(client):
    rahul, ananya = Customer(client, "rahul", 10000), Customer(client, "ananya")
    r = rahul.send(ananya, "2500.50", description="Dinner")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "POSTED"
    assert body["prediction"] is None  # customers never see fraud scores
    assert rahul.balance() == Decimal("7499.50")
    assert ananya.balance() == Decimal("2500.50")
    legs = scalar(
        """SELECT string_agg(entry_type || ':' || amount, ',' ORDER BY sequence_num) FROM ledger_entries e
           JOIN ledger_transactions t ON t.id = e.transaction_id WHERE t.transfer_request_id = :tid""",
        tid=body["id"],
    )
    assert legs == "DEBIT:2500.50,CREDIT:2500.50"


def test_statement_has_running_balance(client):
    rahul, ananya = Customer(client, "rahul", 10000), Customer(client, "ananya")
    rahul.send(ananya, 1000)
    rahul.send(ananya, 500)
    lines = client.get(f"/api/accounts/{rahul.account_id}/statement", headers=rahul.headers).json()["lines"]
    assert [Decimal(l["running_balance"]) for l in lines] == [Decimal("8500"), Decimal("9000"), Decimal("10000")]
    assert lines[0]["counterparty"] == ananya.account_number


def test_cannot_read_another_customers_statement(client):
    rahul, ananya = Customer(client, "rahul"), Customer(client, "ananya")
    assert client.get(f"/api/accounts/{ananya.account_id}/statement", headers=rahul.headers).status_code == 404


def test_insufficient_funds_keeps_a_failed_record(client):
    rahul, ananya = Customer(client, "rahul", 100), Customer(client, "ananya")
    r = rahul.send(ananya, 500)
    assert r.status_code == 422
    assert r.json()["error"] == "INSUFFICIENT_FUNDS"
    failed_id = r.json()["transfer_id"]
    assert scalar("SELECT status FROM transfer_requests WHERE id = :t", t=failed_id) == "FAILED"
    assert scalar("SELECT COUNT(*) FROM audit_logs WHERE action = 'TRANSFER_FAILED'") == 1
    assert scalar("SELECT COUNT(*) FROM ledger_transactions WHERE transfer_request_id = :t", t=failed_id) == 0
    assert rahul.balance() == 100


def test_cannot_debit_someone_elses_account(client):
    rahul, ananya = Customer(client, "rahul"), Customer(client, "ananya", 5000)
    r = rahul.send(rahul, 100, source=ananya.account_id)
    assert r.status_code == 403
    assert r.json()["error"] == "NOT_ACCOUNT_OWNER"
    assert ananya.balance() == 5000


def test_frozen_destination_is_refused(client, admin_headers):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    r = client.post(f"/api/admin/accounts/{ananya.account_id}/status", headers=admin_headers,
                    json={"status": "FROZEN", "reason": "KYC rejected"})
    assert r.status_code == 200
    r = rahul.send(ananya, 100)
    assert r.status_code == 409
    assert r.json()["error"] == "ACCOUNT_NOT_ACTIVE"


def test_unknown_destination_and_same_account(client):
    rahul = Customer(client, "rahul", 5000)
    assert rahul.send("INR-SAV-NOPE0000", 100).status_code == 404
    r = rahul.send(rahul, 100)
    assert r.status_code == 422 and r.json()["error"] == "SAME_ACCOUNT"


def test_amount_must_be_positive_with_two_decimals(client):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    assert rahul.send(ananya, "0").status_code == 422
    assert rahul.send(ananya, "-5").status_code == 422
    assert rahul.send(ananya, "1.005").status_code == 422


def test_idempotent_retry_replays_the_original(client):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    key = str(uuid.uuid4())
    first = rahul.send(ananya, 1000, key=key)
    second = rahul.send(ananya, 1000, key=key)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["replayed"] is True
    assert rahul.balance() == 4000


def test_reused_key_with_different_payload_conflicts(client):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    key = str(uuid.uuid4())
    assert rahul.send(ananya, 1000, key=key).status_code == 201
    r = rahul.send(ananya, 2000, key=key)
    assert r.status_code == 409 and r.json()["error"] == "IDEMPOTENCY_KEY_REUSED"
    assert rahul.balance() == 4000


def test_idempotency_keys_are_scoped_per_sender(client):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya", 5000)
    key = str(uuid.uuid4())
    assert rahul.send(ananya, 100, key=key).status_code == 201
    assert ananya.send(rahul, 100, key=key).status_code == 201


def test_concurrent_withdrawals_never_overdraw(client):
    """10 parallel transfers of 1,000 from an account holding 5,000: exactly five succeed."""
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    results: list[int] = []

    def worker():
        with TestClient(app) as c:
            r = c.post("/api/transfers", headers={**rahul.headers, "Idempotency-Key": str(uuid.uuid4())},
                       json={"source_account_id": rahul.account_id, "destination_account_number": ananya.account_number, "amount": "1000.00"})
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(201) == 5
    assert results.count(422) == 5
    assert rahul.balance() == 0
    assert ananya.balance() == 5000


def test_opposite_transfers_do_not_deadlock(client):
    rahul, ananya = Customer(client, "rahul", 50000), Customer(client, "ananya", 50000)
    errors: list[int] = []

    def worker(sender, receiver):
        with TestClient(app) as c:
            for _ in range(10):
                r = c.post("/api/transfers", headers={**sender.headers, "Idempotency-Key": str(uuid.uuid4())},
                           json={"source_account_id": sender.account_id, "destination_account_number": receiver.account_number, "amount": "100.00"})
                if r.status_code != 201:
                    errors.append(r.status_code)

    threads = [threading.Thread(target=worker, args=(rahul, ananya)), threading.Thread(target=worker, args=(ananya, rahul))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert rahul.balance() + ananya.balance() == 100000


def test_posted_transfer_gets_an_advisory_score(client, staff_headers):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    tid = rahul.send(ananya, 1000).json()["id"]
    r = client.get(f"/api/transfers/{tid}", headers=staff_headers).json()
    assert r["prediction"]["review_status"] == "PENDING"
    assert 0 <= Decimal(r["prediction"]["risk_score"]) <= 1
    assert r["status"] == "POSTED"  # the model never changes the transfer


def test_customer_transfer_list_includes_incoming(client):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    rahul.send(ananya, 100)
    incoming = client.get("/api/transfers", headers=ananya.headers).json()
    assert len(incoming) == 1 and incoming[0]["prediction"] is None


def test_payee_preview_masks_details(client):
    rahul, ananya = Customer(client, "rahul"), Customer(client, "ananya")
    p = client.get(f"/api/accounts/lookup/{ananya.account_number}", headers=rahul.headers).json()
    assert p["account_number_masked"].endswith(ananya.account_number[-4:])
    assert p["account_number_masked"].startswith("XXXX")
    assert p["holder_display_name"] == "A. Tester"


def test_demo_deposit_limit(client):
    rahul = Customer(client, "rahul")
    ok = client.post(f"/api/accounts/{rahul.account_id}/deposit", headers=rahul.headers, json={"amount": "5000.00"})
    assert ok.status_code == 200 and Decimal(ok.json()["cached_balance"]) == 5000
    too_big = client.post(f"/api/accounts/{rahul.account_id}/deposit", headers=rahul.headers, json={"amount": "100000.01"})
    assert too_big.status_code == 422
