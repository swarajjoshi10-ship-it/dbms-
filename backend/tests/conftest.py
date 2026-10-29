"""Tests run against a real PostgreSQL database (never SQLite): the rules under test live in it.

    set TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/finledger_test
    pytest
"""
import os
import uuid
from decimal import Decimal
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/finledger_test"
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "Test@Pass123"
TABLES = (
    "users, customers, accounts, financial_products, transfer_requests, ledger_transactions, ledger_entries, "
    "audit_logs, fraud_predictions, investments, disputes, case_events, saved_payees, investigation_notes, "
    "payee_edges, graph_findings, simulation_runs"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL finledger.allow_truncate = 'on'"))
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("INSERT INTO accounts (account_number, account_type) VALUES ('INR-SYS-CLEARING', 'INTERNAL_CLEARING')"))
    yield


@pytest.fixture
def client():
    return TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def fund(account_id, amount) -> None:
    """Opening deposit of any size straight through the stored procedure."""
    with engine.begin() as conn:
        conn.execute(text("SELECT sp_post_deposit(:a, :amt, 'test funding')"), {"a": account_id, "amt": Decimal(amount)})


class Customer:
    def __init__(self, client: TestClient, username: str, balance: str | int = 0):
        body = {"username": username, "email": f"{username}@example.in", "password": PASSWORD,
                "full_name": f"{username.title()} Tester", "pan_number": "ABCDE1234F"}
        r = client.post("/api/auth/register", json=body)
        assert r.status_code == 201, r.text
        self.client = client
        self.username = username
        self.user_id = r.json()["user"]["id"]
        self.headers = auth(r.json()["access_token"])
        account = client.get("/api/accounts", headers=self.headers).json()[0]
        self.account_id = account["id"]
        self.account_number = account["account_number"]
        if Decimal(balance) > 0:
            fund(self.account_id, balance)

    def balance(self, account_id=None) -> Decimal:
        accounts = self.client.get("/api/accounts", headers=self.headers).json()
        return Decimal(next(a["cached_balance"] for a in accounts if a["id"] == (account_id or self.account_id)))

    def send(self, to: "Customer | str", amount, key: str | None = None, description: str | None = None, source=None):
        number = to.account_number if isinstance(to, Customer) else to
        return self.client.post(
            "/api/transfers",
            json={"source_account_id": source or self.account_id, "destination_account_number": number,
                  "amount": str(amount), "description": description},
            headers={**self.headers, "Idempotency-Key": key or str(uuid.uuid4())},
        )


def make_staff(client: TestClient, username: str, role: str) -> dict:
    with SessionLocal() as db:
        db.add(User(username=username, email=f"{username}@finledger.in", password_hash=hash_password(PASSWORD), role=role))
        db.commit()
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return auth(r.json()["access_token"])


@pytest.fixture
def staff_headers(client):
    return make_staff(client, "priya_investigator", "STAFF")


@pytest.fixture
def admin_headers(client):
    return make_staff(client, "admin_system", "ADMIN")


def scalar(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()
