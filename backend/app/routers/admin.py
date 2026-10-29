import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit
from app.db import get_db
from app.deps import request_meta, require_admin, require_staff
from app.errors import DomainError
from app.models import Account, AuditLog, Customer, TransferRequest, User
from app.schemas import (
    AccountStatusIn, AdminAccountOut, AuditOut, CustomerOut, KycIn, ReconciliationOut, ReconciliationRow, ReverseIn,
    TransferOut, UserOut,
)
from app.services import transfers as transfer_svc

router = APIRouter(prefix="/api", tags=["admin"])


@router.get("/admin/reconciliation", response_model=ReconciliationOut)
def reconcile(admin: User = Depends(require_admin), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """FR13 / BR15: cached_balance = SUM(credits) - SUM(debits) for every account, every
    ledger transaction balanced, and all balances in the system summing to exactly zero."""
    rows = db.execute(text("SELECT * FROM v_account_reconciliation ORDER BY account_number")).mappings().all()
    unbalanced = db.scalar(
        text(
            """
            SELECT COUNT(*) FROM (
                SELECT transaction_id
                  FROM ledger_entries
                 GROUP BY transaction_id
                HAVING SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE -amount END) <> 0
            ) u
            """
        )
    )
    system_total = db.scalar(text("SELECT COALESCE(SUM(cached_balance), 0) FROM accounts"))
    discrepancies = sum(1 for r in rows if r["discrepancy"] != 0)
    result = ReconciliationOut(
        checked_at=datetime.now(UTC), accounts_checked=len(rows), discrepancies=discrepancies,
        unbalanced_transactions=unbalanced, system_total=system_total,
        ok=discrepancies == 0 and unbalanced == 0 and system_total == Decimal("0"),
        rows=[ReconciliationRow(**{k: r[k] for k in ReconciliationRow.model_fields}) for r in rows],
    )
    write_audit(db, admin.id, "RECONCILIATION_RUN", "LEDGER", "all",
                {"ok": result.ok, "discrepancies": discrepancies, "unbalanced": unbalanced}, meta)
    db.commit()
    return result


@router.post("/admin/transfers/{transfer_id}/reverse", response_model=TransferOut)
def reverse(transfer_id: uuid.UUID, body: ReverseIn, admin: User = Depends(require_admin), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """FR12: admin-only CORRECTION_REVERSAL posting."""
    transfer_svc.reverse_transfer(db, admin, transfer_id, body.reason, meta)
    transfer = db.get(TransferRequest, transfer_id)
    db.refresh(transfer)
    return transfer_svc.to_out(db, transfer)


@router.get("/admin/accounts", response_model=list[AdminAccountOut])
def all_accounts(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Account, Customer.full_name, User.username, Customer.kyc_status)
        .outerjoin(Customer, Customer.id == Account.customer_id)
        .outerjoin(User, User.id == Customer.user_id)
        .order_by(Account.account_number)
    )
    return [
        AdminAccountOut.model_validate(a).model_copy(update={"owner_name": name, "owner_username": uname, "kyc_status": kyc})
        for a, name, uname, kyc in rows
    ]


@router.post("/admin/accounts/{account_id}/status", response_model=AdminAccountOut)
def set_account_status(
    account_id: uuid.UUID, body: AccountStatusIn, admin: User = Depends(require_admin),
    db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta),
):
    account = db.scalar(select(Account).where(Account.id == account_id).with_for_update(key_share=True))  # FOR NO KEY UPDATE
    if account is None:
        raise DomainError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    if account.account_type == "INTERNAL_CLEARING":
        raise DomainError(422, "INTERNAL_ACCOUNT", "The clearing account cannot be frozen or closed")
    if body.status == "CLOSED" and account.cached_balance != 0:
        raise DomainError(422, "BALANCE_NOT_ZERO", "Only an account with a zero balance can be closed")
    if account.status == "CLOSED":
        raise DomainError(409, "ACCOUNT_CLOSED", "A closed account cannot be reopened")
    previous = account.status
    account.status = body.status
    account.version += 1
    account.updated_at = datetime.now(UTC)
    write_audit(db, admin.id, "ACCOUNT_STATUS_CHANGED", "ACCOUNT", account.id,
                {"from": previous, "to": body.status, "reason": body.reason}, meta)
    db.commit()
    return AdminAccountOut.model_validate(account)


@router.get("/admin/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.role, User.username)).all()


@router.get("/admin/customers", response_model=list[CustomerOut])
def list_customers(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(Customer).order_by(Customer.full_name)).all()


@router.post("/admin/customers/{customer_id}/kyc", response_model=CustomerOut)
def set_kyc(customer_id: uuid.UUID, body: KycIn, staff: User = Depends(require_staff), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise DomainError(404, "CUSTOMER_NOT_FOUND", "Customer not found")
    previous = customer.kyc_status
    customer.kyc_status = body.kyc_status
    customer.updated_at = datetime.now(UTC)
    write_audit(db, staff.id, "KYC_STATUS_CHANGED", "CUSTOMER", customer.id, {"from": previous, "to": body.kyc_status}, meta)
    db.commit()
    return customer


@router.get("/audit", response_model=list[AuditOut])
def audit_trail(
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    query = select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.actor_user_id).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action.strip().upper())
    return [AuditOut.model_validate(log).model_copy(update={"actor": username}) for log, username in db.execute(query)]


@router.get("/reports/summary")
def summary(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Headline numbers for the staff dashboard (aggregates over the core tables)."""
    totals = db.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM customers)                                                   AS customers,
              (SELECT COUNT(*) FROM accounts WHERE customer_id IS NOT NULL)                      AS customer_accounts,
              (SELECT COALESCE(SUM(cached_balance), 0) FROM accounts
                WHERE account_type <> 'INTERNAL_CLEARING')                                       AS customer_liabilities,
              (SELECT COUNT(*) FROM transfer_requests WHERE status = 'POSTED')                   AS posted_transfers,
              (SELECT COUNT(*) FROM transfer_requests WHERE status = 'FAILED')                   AS failed_transfers,
              (SELECT COUNT(*) FROM transfer_requests WHERE status = 'REVERSED')                 AS reversed_transfers,
              (SELECT COUNT(*) FROM fraud_predictions
                WHERE review_status = 'PENDING' AND risk_score >= 0.40)                          AS pending_alerts,
              (SELECT COUNT(*) FROM disputes WHERE status IN ('OPEN', 'INVESTIGATING'))          AS open_disputes
            """
        )
    ).mappings().one()
    daily = db.execute(
        text(
            """
            SELECT ((created_at AT TIME ZONE 'UTC') + INTERVAL '5 hours 30 minutes')::date AS day,  -- IST
                   COUNT(*) FILTER (WHERE status IN ('POSTED', 'REVERSED')) AS posted,
                   COUNT(*) FILTER (WHERE status = 'FAILED')               AS failed,
                   COALESCE(SUM(amount) FILTER (WHERE status IN ('POSTED', 'REVERSED')), 0) AS volume
              FROM transfer_requests
             WHERE created_at > now() - INTERVAL '14 days'
             GROUP BY 1 ORDER BY 1
            """
        )
    ).mappings().all()
    bands = db.execute(
        text("SELECT decision, COUNT(*) AS n FROM fraud_predictions GROUP BY decision ORDER BY decision")
    ).mappings().all()
    return {"totals": dict(totals), "daily": [dict(r) for r in daily], "risk_bands": [dict(r) for r in bands]}
