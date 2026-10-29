"""ORM mappings of the tables created by the Alembic migrations.

The migrations are the source of truth for the schema (constraints, triggers, procedures);
these classes only describe the columns so the API can query them.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    customer: Mapped["Customer | None"] = relationship(back_populates="user", uselist=False)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20))
    pan_number: Mapped[str | None] = mapped_column(String(10))
    kyc_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    user: Mapped[User] = relationship(back_populates="customer")
    accounts: Mapped[list["Account"]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    account_number: Mapped[str] = mapped_column(String(32))
    account_type: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    cached_balance: Mapped[Decimal] = mapped_column(Numeric(15, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()

    customer: Mapped[Customer | None] = relationship(back_populates="accounts")


class FinancialProduct(Base):
    __tablename__ = "financial_products"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(32))
    product_type: Mapped[str] = mapped_column(String(20))
    annual_yield_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    term_months: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = _created()


class TransferRequest(Base):
    __tablename__ = "transfer_requests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(String(64))
    source_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    request_hash: Mapped[str] = mapped_column(String(64))
    source_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    destination_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(20))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source_account: Mapped[Account] = relationship(foreign_keys=[source_account_id])
    destination_account: Mapped[Account] = relationship(foreign_keys=[destination_account_id])
    prediction: Mapped["FraudPrediction | None"] = relationship(back_populates="transfer", uselist=False)


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    transfer_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transfer_requests.id"))
    transaction_type: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_transactions.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    entry_type: Mapped[str] = mapped_column(String(6))
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    sequence_num: Mapped[int] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(64))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class FraudPrediction(Base):
    __tablename__ = "fraud_predictions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    transfer_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transfer_requests.id"))
    model_version: Mapped[str] = mapped_column(String(30))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    decision: Mapped[str] = mapped_column(String(20))
    rule_flags: Mapped[list] = mapped_column(JSONB, default=list)
    feature_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    explanation: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    review_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    transfer: Mapped[TransferRequest] = relationship(back_populates="prediction")


class Investment(Base):
    __tablename__ = "investments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_products.id"))
    investment_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    ledger_transaction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ledger_transactions.id"))
    principal: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    annual_yield_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    start_date: Mapped[date] = mapped_column(Date)
    maturity_date: Mapped[date] = mapped_column(Date)
    expected_maturity_value: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = _created()

    product: Mapped[FinancialProduct] = relationship()


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    transfer_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transfer_requests.id"))
    reason: Mapped[str] = mapped_column(String(30))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship()
    transfer: Mapped[TransferRequest] = relationship()
    events: Mapped[list["CaseEvent"]] = relationship(order_by="CaseEvent.created_at")


class CaseEvent(Base):
    __tablename__ = "case_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    dispute_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disputes.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    actor: Mapped[User | None] = relationship()


class SavedPayee(Base):
    __tablename__ = "saved_payees"
    id: Mapped[uuid.UUID] = _uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    payee_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    nickname: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = _created()

    payee_account: Mapped[Account] = relationship()


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    fraud_prediction_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fraud_predictions.id"))
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()

    author: Mapped[User] = relationship()


class PayeeEdge(Base):
    __tablename__ = "payee_edges"
    id: Mapped[uuid.UUID] = _uuid_pk()
    source_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    destination_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    transfer_count: Mapped[int] = mapped_column(Integer)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    first_seen_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()


class GraphFinding(Base):
    __tablename__ = "graph_findings"
    id: Mapped[uuid.UUID] = _uuid_pk()
    finding_type: Mapped[str] = mapped_column(String(30))
    primary_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    involved_account_ids: Mapped[list] = mapped_column(JSONB, default=list)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    severity: Mapped[str] = mapped_column(String(10))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = _created()

    primary_account: Mapped[Account] = relationship()


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    run_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    model_version: Mapped[str] = mapped_column(String(30))
    scenario: Mapped[dict] = mapped_column(JSONB, default=dict)
    n_samples: Mapped[int] = mapped_column(Integer)
    accuracy: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    precision_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    recall_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    f1_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    confusion: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()
