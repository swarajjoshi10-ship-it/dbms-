import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import RequestMeta
from app.db import get_db
from app.deps import get_current_user, request_meta, require_customer
from app.errors import DomainError
from app.models import Account, Customer, TransferRequest, User
from app.schemas import TransferIn, TransferOut
from app.services import transfers as svc

router = APIRouter(prefix="/api/transfers", tags=["transfers"])


@router.post("", response_model=TransferOut, status_code=201)
def create_transfer(
    body: TransferIn,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=64),
    user: User = Depends(require_customer),
    db: Session = Depends(get_db),
    meta: RequestMeta = Depends(request_meta),
):
    """FR5–FR7. Send the same Idempotency-Key on a retry to get the original result back."""
    transfer, replayed = svc.create_transfer(db, user, idempotency_key, body, meta)
    if replayed:
        response.status_code = 200
        if transfer.status == "FAILED":
            raise DomainError(422, "TRANSFER_FAILED", transfer.failure_reason or "Transfer failed", {"transfer_id": str(transfer.id)})
    return svc.to_out(db, transfer, replayed, include_prediction=False)  # fraud scores are for staff eyes only


@router.get("", response_model=list[TransferOut])
def list_transfers(
    status: Literal["PENDING", "POSTED", "FAILED", "REVERSED"] | None = None,
    account_number: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Customers see transfers into or out of their accounts; staff and admins see all."""
    query = select(TransferRequest).order_by(TransferRequest.created_at.desc()).limit(limit)
    if user.role == "CUSTOMER":
        own = select(Account.id).join(Customer, Customer.id == Account.customer_id).where(Customer.user_id == user.id)
        query = query.where(
            or_(
                TransferRequest.source_user_id == user.id,
                (TransferRequest.destination_account_id.in_(own)) & (TransferRequest.status != "FAILED"),
            )
        )
    if status:
        query = query.where(TransferRequest.status == status)
    if account_number:
        acc = select(Account.id).where(Account.account_number == account_number.strip().upper())
        query = query.where(or_(TransferRequest.source_account_id.in_(acc), TransferRequest.destination_account_id.in_(acc)))
    return [svc.to_out(db, t, include_prediction=user.role != "CUSTOMER") for t in db.scalars(query)]


@router.get("/{transfer_id}", response_model=TransferOut)
def get_transfer(transfer_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    transfer = db.get(TransferRequest, transfer_id)
    if transfer is None:
        raise DomainError(404, "TRANSFER_NOT_FOUND", "Transfer not found")
    if user.role == "CUSTOMER" and transfer.source_user_id != user.id:
        dst = db.get(Account, transfer.destination_account_id)
        owner = db.get(Customer, dst.customer_id) if dst.customer_id else None
        if owner is None or owner.user_id != user.id or transfer.status == "FAILED":
            raise DomainError(404, "TRANSFER_NOT_FOUND", "Transfer not found")
    return svc.to_out(db, transfer, include_prediction=user.role != "CUSTOMER")
