import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

# Money is always a Decimal with two places (NUMERIC(15,2) in the database).
Money = Annotated[Decimal, Field(gt=0, max_digits=15, decimal_places=2)]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.]+$")]
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    pan_number: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")] | None = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(ORM):
    id: uuid.UUID
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class CustomerOut(ORM):
    id: uuid.UUID
    full_name: str
    phone: str | None
    pan_number: str | None
    kyc_status: str


class MeOut(BaseModel):
    user: UserOut
    customer: CustomerOut | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------- accounts ----------
class AccountOut(ORM):
    id: uuid.UUID
    account_number: str
    account_type: str
    currency: str
    cached_balance: Decimal
    status: str
    created_at: datetime


class AdminAccountOut(AccountOut):
    owner_name: str | None = None
    owner_username: str | None = None
    kyc_status: str | None = None


class OpenAccountIn(BaseModel):
    account_type: Literal["SAVINGS", "CURRENT"]


class DepositIn(BaseModel):
    amount: Money


class StatementLine(BaseModel):
    entry_id: uuid.UUID
    transaction_id: uuid.UUID
    transaction_type: str
    description: str
    transfer_request_id: uuid.UUID | None
    entry_type: str
    amount: Decimal
    running_balance: Decimal
    counterparty: str | None
    created_at: datetime


class StatementOut(BaseModel):
    account: AccountOut
    total: int
    lines: list[StatementLine]


class PayeePreview(BaseModel):
    account_id: uuid.UUID
    account_number_masked: str
    holder_display_name: str
    account_type: str
    status: str


class AccountStatusIn(BaseModel):
    status: Literal["ACTIVE", "FROZEN", "CLOSED"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]


class KycIn(BaseModel):
    kyc_status: Literal["PENDING", "VERIFIED", "REJECTED"]


# ---------- payees ----------
class SavedPayeeIn(BaseModel):
    account_number: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=32)]
    nickname: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class SavedPayeeOut(BaseModel):
    id: uuid.UUID
    nickname: str
    account_id: uuid.UUID
    account_number_masked: str
    holder_display_name: str
    created_at: datetime


# ---------- transfers ----------
class TransferIn(BaseModel):
    source_account_id: uuid.UUID
    destination_account_number: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, max_length=32)]
    amount: Money
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=140)] | None = None


class PredictionBrief(ORM):
    id: uuid.UUID
    model_version: str
    risk_score: Decimal
    decision: str
    rule_flags: list
    explanation: str
    review_status: str


class TransferOut(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    status: str
    amount: Decimal
    currency: str
    source_account_id: uuid.UUID
    source_account_number: str
    destination_account_id: uuid.UUID
    destination_account_number: str
    failure_reason: str | None
    created_at: datetime
    posted_at: datetime | None
    replayed: bool = False
    prediction: PredictionBrief | None = None


class ReverseIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]


# ---------- products & investments ----------
ProductType = Literal["FIXED_DEPOSIT", "RECURRING_DEPOSIT", "MUTUAL_FUND", "TREASURY_BILL"]


class ProductOut(ORM):
    id: uuid.UUID
    name: str
    code: str
    product_type: str
    annual_yield_rate: Decimal
    min_amount: Decimal
    term_months: int
    is_active: bool


class ProductIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)]
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z0-9-]{3,32}$")]
    product_type: ProductType
    annual_yield_rate: Annotated[Decimal, Field(ge=0, le=99.99, decimal_places=2)]
    min_amount: Money
    term_months: Annotated[int, Field(gt=0, le=600)]
    is_active: bool = True


class ProductPatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=100)] | None = None
    annual_yield_rate: Annotated[Decimal, Field(ge=0, le=99.99, decimal_places=2)] | None = None
    min_amount: Money | None = None
    is_active: bool | None = None


class InvestIn(BaseModel):
    product_id: uuid.UUID
    funding_account_id: uuid.UUID
    amount: Money


class InvestmentOut(BaseModel):
    id: uuid.UUID
    product_code: str
    product_name: str
    product_type: str
    principal: Decimal
    annual_yield_rate: Decimal
    start_date: date
    maturity_date: date
    expected_maturity_value: Decimal
    status: str


# ---------- fraud ----------
ReviewStatus = Literal["CLEARED", "CONFIRMED_FRAUD", "ESCALATED"]


class AlertOut(BaseModel):
    id: uuid.UUID
    transfer_request_id: uuid.UUID
    model_version: str
    risk_score: Decimal
    decision: str
    rule_flags: list
    feature_snapshot: dict
    explanation: str
    review_status: str
    reviewed_by: str | None
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    amount: Decimal
    transfer_status: str
    source_account_number: str
    destination_account_number: str
    sender_username: str


class NoteOut(BaseModel):
    id: uuid.UUID
    author: str
    note: str
    created_at: datetime


class AlertDetailOut(AlertOut):
    notes: list[NoteOut]


class ReviewIn(BaseModel):
    review_status: ReviewStatus
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


class NoteIn(BaseModel):
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class LabRunIn(BaseModel):
    n_samples: Annotated[int, Field(ge=100, le=20000)] = 2000
    fraud_rate: Annotated[float, Field(gt=0, lt=0.5)] = 0.08
    seed: int | None = None


class LabRunOut(ORM):
    id: uuid.UUID
    model_version: str
    scenario: dict
    n_samples: int
    accuracy: Decimal
    precision_score: Decimal
    recall_score: Decimal
    f1_score: Decimal
    confusion: dict
    created_at: datetime


class GraphFindingOut(BaseModel):
    id: uuid.UUID
    finding_type: str
    primary_account_number: str
    involved_account_numbers: list[str]
    total_amount: Decimal
    severity: str
    details: dict
    status: str
    created_at: datetime


class FindingStatusIn(BaseModel):
    status: Literal["OPEN", "DISMISSED", "CONFIRMED"]


# ---------- disputes ----------
DisputeReason = Literal["UNAUTHORIZED", "WRONG_RECIPIENT", "WRONG_AMOUNT", "SCAM", "OTHER"]


class DisputeIn(BaseModel):
    transfer_request_id: uuid.UUID
    reason: DisputeReason
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class CaseEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    message: str
    actor: str | None
    created_at: datetime


class DisputeOut(BaseModel):
    id: uuid.UUID
    transfer_request_id: uuid.UUID
    customer_name: str
    reason: str
    description: str
    status: str
    assigned_staff: str | None
    resolution_notes: str | None
    amount: Decimal
    transfer_status: str
    destination_account_number: str
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    events: list[CaseEventOut] = []


class DisputeCommentIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class DisputeResolveIn(BaseModel):
    outcome: Literal["RESOLVED_UPHELD", "RESOLVED_REJECTED"]
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=2000)]


# ---------- admin / audit / reports ----------
class ReconciliationRow(BaseModel):
    account_number: str
    account_type: str
    status: str
    cached_balance: Decimal
    ledger_balance: Decimal
    discrepancy: Decimal
    leg_count: int


class ReconciliationOut(BaseModel):
    checked_at: datetime
    accounts_checked: int
    discrepancies: int
    unbalanced_transactions: int
    system_total: Decimal
    ok: bool
    rows: list[ReconciliationRow]


class AuditOut(ORM):
    id: int
    actor: str | None = None
    action: str
    entity_type: str
    entity_id: str
    ip_address: str | None
    metadata_json: dict
    created_at: datetime
