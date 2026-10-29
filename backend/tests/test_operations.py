"""Admin corrections, reconciliation, fraud review, graph signals, disputes and investments."""
from decimal import Decimal

from tests.conftest import Customer, scalar


def test_admin_reversal_is_a_new_posting(client, admin_headers):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    tid = rahul.send(ananya, 1200).json()["id"]
    r = client.post(f"/api/admin/transfers/{tid}/reverse", headers=admin_headers, json={"reason": "Sent to wrong person"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REVERSED"
    assert rahul.balance() == 5000 and ananya.balance() == 0
    # Both the original and the correction remain on record.
    assert scalar("SELECT COUNT(*) FROM ledger_transactions WHERE transaction_type = 'CUSTOMER_TRANSFER'") == 1
    assert scalar("SELECT COUNT(*) FROM ledger_transactions WHERE transaction_type = 'CORRECTION_REVERSAL'") == 1
    assert scalar("SELECT COUNT(*) FROM ledger_transactions WHERE description LIKE :d", d=f"Reversal of transfer {tid}%") == 1
    again = client.post(f"/api/admin/transfers/{tid}/reverse", headers=admin_headers, json={"reason": "Twice by mistake"})
    assert again.status_code == 409


def test_reversal_needs_funds_at_destination(client, admin_headers):
    rahul, ananya, vikram = Customer(client, "rahul", 5000), Customer(client, "ananya"), Customer(client, "vikram")
    tid = rahul.send(ananya, 1000).json()["id"]
    ananya.send(vikram, 1000)
    r = client.post(f"/api/admin/transfers/{tid}/reverse", headers=admin_headers, json={"reason": "Customer complaint"})
    assert r.status_code == 422 and r.json()["error"] == "INSUFFICIENT_FUNDS"


def test_staff_cannot_reverse(client, staff_headers):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    tid = rahul.send(ananya, 100).json()["id"]
    assert client.post(f"/api/admin/transfers/{tid}/reverse", headers=staff_headers, json={"reason": "Not allowed"}).status_code == 403


def test_reconciliation_proves_the_books(client, admin_headers):
    rahul, ananya = Customer(client, "rahul", 50000), Customer(client, "ananya", 1000)
    rahul.send(ananya, 7000)
    ananya.send(rahul, 300)
    rec = client.get("/api/admin/reconciliation", headers=admin_headers).json()
    assert rec["ok"] is True
    assert rec["discrepancies"] == 0 and rec["unbalanced_transactions"] == 0
    assert Decimal(rec["system_total"]) == 0


def test_closing_requires_zero_balance(client, admin_headers):
    rahul = Customer(client, "rahul", 10)
    r = client.post(f"/api/admin/accounts/{rahul.account_id}/status", headers=admin_headers, json={"status": "CLOSED", "reason": "Customer request"})
    assert r.status_code == 422


def test_high_risk_transfer_is_flagged_with_reasons(client, staff_headers):
    sneha, mule = Customer(client, "sneha", 300000), Customer(client, "mule")
    r = sneha.send(mule, 290000)  # new payee, huge amount, drains ~97% of the balance
    assert r.status_code == 201
    alerts = client.get("/api/fraud/alerts", headers=staff_headers).json()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["decision"] in ("MEDIUM_RISK", "HIGH_RISK")
    assert {"HIGH_AMOUNT", "NEW_PAYEE_LARGE", "BALANCE_DRAIN"} <= set(alert["rule_flags"])
    assert "advisory" in alert["explanation"]


def test_alert_review_workflow(client, staff_headers):
    sneha, mule = Customer(client, "sneha", 300000), Customer(client, "mule")
    sneha.send(mule, 290000)
    alert_id = client.get("/api/fraud/alerts", headers=staff_headers).json()[0]["id"]
    no_notes = client.post(f"/api/fraud/alerts/{alert_id}/review", headers=staff_headers, json={"review_status": "CLEARED", "notes": ""})
    assert no_notes.status_code == 422
    esc = client.post(f"/api/fraud/alerts/{alert_id}/review", headers=staff_headers,
                      json={"review_status": "ESCALATED", "notes": "Called customer, no answer"})
    assert esc.status_code == 200 and esc.json()["review_status"] == "ESCALATED"
    done = client.post(f"/api/fraud/alerts/{alert_id}/review", headers=staff_headers,
                       json={"review_status": "CONFIRMED_FRAUD", "notes": "Customer confirmed a scam call"})
    assert done.json()["review_status"] == "CONFIRMED_FRAUD"
    assert len(done.json()["notes"]) == 2
    final = client.post(f"/api/fraud/alerts/{alert_id}/review", headers=staff_headers,
                        json={"review_status": "CLEARED", "notes": "Changing my mind"})
    assert final.status_code == 409
    assert scalar("SELECT COUNT(*) FROM audit_logs WHERE action = 'FRAUD_ALERT_REVIEWED'") == 2


def test_fraud_lab_stores_metrics(client, staff_headers):
    r = client.post("/api/fraud/lab/runs", headers=staff_headers, json={"n_samples": 1000, "fraud_rate": 0.1, "seed": 3})
    assert r.status_code == 201
    run = r.json()
    assert Decimal(run["accuracy"]) > Decimal("0.85")
    assert sum(run["confusion"].values()) == 1000


def test_graph_scan_finds_a_money_cycle(client, staff_headers):
    a, b, c = Customer(client, "aaa", 50000), Customer(client, "bbb"), Customer(client, "ccc")
    a.send(b, 20000)
    b.send(c, 19000)
    c.send(a, 18000)
    findings = client.post("/api/graph/scan", headers=staff_headers).json()
    cycles = [f for f in findings if f["finding_type"] == "CYCLE"]
    assert len(cycles) == 1
    assert set(cycles[0]["involved_account_numbers"]) == {a.account_number, b.account_number, c.account_number}
    assert client.post("/api/graph/scan", headers=staff_headers).json() == []  # no duplicates


def test_dispute_lifecycle(client, staff_headers):
    rahul, ananya, vikram = Customer(client, "rahul", 5000), Customer(client, "ananya"), Customer(client, "vikram")
    tid = rahul.send(ananya, 900).json()["id"]
    body = {"transfer_request_id": tid, "reason": "WRONG_RECIPIENT", "description": "Meant to pay my landlord"}
    d = client.post("/api/disputes", headers=rahul.headers, json=body)
    assert d.status_code == 201
    dispute_id = d.json()["id"]
    assert client.post("/api/disputes", headers=rahul.headers, json=body).status_code == 409
    assert client.get(f"/api/disputes/{dispute_id}", headers=vikram.headers).status_code == 404
    assert client.post(f"/api/disputes/{dispute_id}/assign", headers=staff_headers).json()["status"] == "INVESTIGATING"
    resolved = client.post(f"/api/disputes/{dispute_id}/resolve", headers=staff_headers,
                           json={"outcome": "RESOLVED_UPHELD", "notes": "Recipient agreed to return"})
    assert resolved.json()["status"] == "RESOLVED_UPHELD"
    assert [e["event_type"] for e in resolved.json()["events"]] == ["OPENED", "ASSIGNED", "RESOLVED"]


def test_investment_purchase(client, admin_headers):
    client.post("/api/products", headers=admin_headers, json={
        "name": "12-Month Standard Fixed Deposit", "code": "FD-12M-STD", "product_type": "FIXED_DEPOSIT",
        "annual_yield_rate": "7.10", "min_amount": "10000.00", "term_months": 12})
    rahul = Customer(client, "rahul", 50000)
    product = client.get("/api/products", headers=rahul.headers).json()[0]
    low = client.post("/api/investments", headers=rahul.headers,
                      json={"product_id": product["id"], "funding_account_id": rahul.account_id, "amount": "5000.00"})
    assert low.status_code == 422 and low.json()["error"] == "BELOW_MINIMUM"
    r = client.post("/api/investments", headers=rahul.headers,
                    json={"product_id": product["id"], "funding_account_id": rahul.account_id, "amount": "20000.00"})
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["expected_maturity_value"]) == Decimal("21420.00")
    accounts = client.get("/api/accounts", headers=rahul.headers).json()
    inv = next(a for a in accounts if a["account_type"] == "INVESTMENT")
    assert Decimal(inv["cached_balance"]) == 20000 and rahul.balance() == 30000
    assert client.get("/api/admin/reconciliation", headers=admin_headers).json()["ok"] is True


def test_audit_trail_is_visible_to_staff(client, staff_headers):
    rahul, ananya = Customer(client, "rahul", 5000), Customer(client, "ananya")
    rahul.send(ananya, 10)
    actions = {a["action"] for a in client.get("/api/audit", headers=staff_headers).json()}
    assert {"USER_REGISTERED", "TRANSFER_POSTED", "AUTH_LOGIN_SUCCESS"} <= actions
