import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit
from app.config import settings
from app.db import get_db
from app.deps import get_current_user, get_customer, request_meta
from app.errors import DomainError
from app.models import Account, Customer, SavedPayee, User
from app.schemas import (
    AccountOut, DepositIn, OpenAccountIn, PayeePreview, SavedPayeeIn, SavedPayeeOut, StatementOut,
)
from app.services import accounts as svc

router = APIRouter(prefix="/api", tags=["accounts"])


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    return svc.customer_accounts(db, customer)


@router.post("/accounts", response_model=AccountOut, status_code=201)
def open_new_account(
    body: OpenAccountIn,
    customer: Customer = Depends(get_customer),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(request_meta),
):
    if svc.count_accounts(db, customer, body.account_type) >= 3:
        raise DomainError(422, "ACCOUNT_LIMIT", f"You can hold at most three {body.account_type.lower()} accounts")
    account = svc.open_account(db, customer, body.account_type)
    write_audit(db, customer.user_id, "ACCOUNT_OPENED", "ACCOUNT", account.id, {"account_number": account.account_number}, meta)
    db.commit()
    return account


@router.post("/accounts/{account_id}/deposit", response_model=AccountOut)
def demo_deposit(
    account_id: uuid.UUID,
    body: DepositIn,
    customer: Customer = Depends(get_customer),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(request_meta),
):
    if body.amount > settings.max_demo_deposit:
        raise DomainError(422, "DEPOSIT_LIMIT", f"Demo deposits are limited to ₹{settings.max_demo_deposit:,.2f}")
    account = svc.own_account(db, customer, account_id)
    svc.post_deposit(db, customer.user, account, body.amount, meta)
    return account


@router.get("/accounts/{account_id}/statement", response_model=StatementOut)
def account_statement(
    account_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """FR8. Customers see their own accounts; staff and admins may open any statement."""
    account = db.get(Account, account_id)
    if account is None:
        raise DomainError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    if user.role == "CUSTOMER":
        customer = db.scalar(select(Customer).where(Customer.user_id == user.id))
        if customer is None or account.customer_id != customer.id:
            raise DomainError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    return svc.statement(db, account, limit, offset)


@router.get("/accounts/lookup/{account_number}", response_model=PayeePreview)
def lookup_payee(account_number: str, _: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    """PayeeGuard: confirm who you are paying (masked number and initials) before sending."""
    account = svc.find_by_number(db, account_number)
    if account.account_type not in ("SAVINGS", "CURRENT"):
        raise DomainError(404, "ACCOUNT_NOT_FOUND", "No account with that number")
    return svc.payee_preview(db, account)


def _payee_out(db: Session, payee: SavedPayee) -> SavedPayeeOut:
    preview = svc.payee_preview(db, payee.payee_account)
    return SavedPayeeOut(
        id=payee.id, nickname=payee.nickname, account_id=payee.payee_account_id,
        account_number_masked=preview.account_number_masked, holder_display_name=preview.holder_display_name,
        created_at=payee.created_at,
    )


@router.get("/payees", response_model=list[SavedPayeeOut])
def list_payees(customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    payees = db.scalars(select(SavedPayee).where(SavedPayee.customer_id == customer.id).order_by(SavedPayee.nickname))
    return [_payee_out(db, p) for p in payees]


@router.post("/payees", response_model=SavedPayeeOut, status_code=201)
def add_payee(body: SavedPayeeIn, customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    account = svc.find_by_number(db, body.account_number)
    if account.customer_id == customer.id or account.account_type not in ("SAVINGS", "CURRENT"):
        raise DomainError(422, "INVALID_PAYEE", "That account cannot be saved as a payee")
    payee = SavedPayee(customer_id=customer.id, payee_account_id=account.id, nickname=body.nickname)
    db.add(payee)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "PAYEE_EXISTS", "This payee is already saved") from None
    return _payee_out(db, payee)


@router.get("/payees/{payee_id}/account-number")
def payee_account_number(payee_id: uuid.UUID, customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    """The full number of a payee the customer saved themselves (used to pre-fill a transfer)."""
    payee = db.get(SavedPayee, payee_id)
    if payee is None or payee.customer_id != customer.id:
        raise DomainError(404, "PAYEE_NOT_FOUND", "Payee not found")
    return {"account_number": payee.payee_account.account_number}


@router.delete("/payees/{payee_id}", status_code=204)
def delete_payee(payee_id: uuid.UUID, customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    payee = db.get(SavedPayee, payee_id)
    if payee is None or payee.customer_id != customer.id:
        raise DomainError(404, "PAYEE_NOT_FOUND", "Payee not found")
    db.delete(payee)
    db.commit()
