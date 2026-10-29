from tests.conftest import PASSWORD, Customer, scalar


def test_register_login_and_me(client):
    c = Customer(client, "rahul")
    r = client.post("/api/auth/login", json={"username": "rahul", "password": PASSWORD})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["user"]["role"] == "CUSTOMER"
    assert me["customer"]["kyc_status"] == "PENDING"
    assert c.account_number.startswith("INR-SAV-")


def test_password_is_stored_as_argon2_hash(client):
    Customer(client, "rahul")
    stored = scalar("SELECT password_hash FROM users WHERE username = 'rahul'")
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


def test_duplicate_username_conflicts(client):
    Customer(client, "rahul")
    r = client.post("/api/auth/register", json={"username": "rahul", "email": "other@example.in",
                                                "password": PASSWORD, "full_name": "Someone Else"})
    assert r.status_code == 409


def test_wrong_password_is_refused_and_audited(client):
    Customer(client, "rahul")
    r = client.post("/api/auth/login", json={"username": "rahul", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["error"] == "INVALID_CREDENTIALS"
    assert scalar("SELECT COUNT(*) FROM audit_logs WHERE action = 'AUTH_LOGIN_FAILURE'") == 1


def test_routes_require_a_token(client):
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/accounts", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_customer_cannot_use_staff_routes(client):
    c = Customer(client, "rahul")
    assert client.get("/api/fraud/alerts", headers=c.headers).status_code == 403
    assert client.get("/api/admin/reconciliation", headers=c.headers).status_code == 403
    assert client.get("/api/audit", headers=c.headers).status_code == 403


def test_validation_errors_are_clean(client):
    r = client.post("/api/auth/register", json={"username": "x", "email": "bad", "password": "short", "full_name": "A"})
    assert r.status_code == 422
    assert r.json()["error"] == "VALIDATION_ERROR"
    assert "Traceback" not in r.text
