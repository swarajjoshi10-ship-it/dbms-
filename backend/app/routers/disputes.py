import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit
from app.db import get_db
from app.deps import get_current_user, get_customer, request_meta, require_staff
from app.errors import DomainError
from app.models import Account, CaseEvent, Customer, Dispute, TransferRequest, User
from app.schemas import CaseEventOut, DisputeCommentIn, DisputeIn, DisputeOut, DisputeResolveIn

router = APIRouter(prefix="/api/disputes", tags=["disputes"])


def _out(db: Session, d: Dispute, with_events: bool = False) -> DisputeOut:
    staff = db.get(User, d.assigned_staff_id) if d.assigned_staff_id else None
    events = []
    if with_events:
        events = [
            CaseEventOut(id=e.id, event_type=e.event_type, message=e.message,
                         actor=e.actor.username if e.actor else None, created_at=e.created_at)
            for e in d.events
        ]
    return DisputeOut(
        id=d.id, transfer_request_id=d.transfer_request_id, customer_name=d.customer.full_name, reason=d.reason,
        description=d.description, status=d.status, assigned_staff=staff.username if staff else None,
        resolution_notes=d.resolution_notes, amount=d.transfer.amount, transfer_status=d.transfer.status,
        destination_account_number=db.get(Account, d.transfer.destination_account_id).account_number,
        created_at=d.created_at, updated_at=d.updated_at, resolved_at=d.resolved_at, events=events,
    )


def _event(db: Session, dispute: Dispute, actor: User | None, event_type: str, message: str) -> None:
    db.add(CaseEvent(dispute_id=dispute.id, actor_user_id=actor.id if actor else None, event_type=event_type, message=message))


def _load(db: Session, dispute_id: uuid.UUID, user: User) -> Dispute:
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        raise DomainError(404, "DISPUTE_NOT_FOUND", "Dispute not found")
    if user.role == "CUSTOMER" and dispute.customer.user_id != user.id:
        raise DomainError(404, "DISPUTE_NOT_FOUND", "Dispute not found")
    return dispute


@router.post("", response_model=DisputeOut, status_code=201)
def file_dispute(body: DisputeIn, customer: Customer = Depends(get_customer), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """FR11: a customer disputes a transfer they sent."""
    transfer = db.get(TransferRequest, body.transfer_request_id)
    if transfer is None or transfer.source_user_id != customer.user_id:
        raise DomainError(404, "TRANSFER_NOT_FOUND", "Transfer not found")
    if transfer.status != "POSTED":
        raise DomainError(422, "NOT_DISPUTABLE", f"A {transfer.status.lower()} transfer cannot be disputed")
    dispute = Dispute(customer_id=customer.id, transfer_request_id=transfer.id, reason=body.reason, description=body.description)
    db.add(dispute)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "DISPUTE_EXISTS", "This transfer already has an open dispute") from None
    _event(db, dispute, customer.user, "OPENED", f"Dispute opened: {body.reason.replace('_', ' ').lower()}")
    write_audit(db, customer.user_id, "DISPUTE_OPENED", "DISPUTE", dispute.id, {"transfer_id": str(transfer.id)}, meta)
    db.commit()
    db.refresh(dispute)
    return _out(db, dispute, with_events=True)


@router.get("", response_model=list[DisputeOut])
def list_disputes(
    status: Literal["OPEN", "INVESTIGATING", "RESOLVED_UPHELD", "RESOLVED_REJECTED", "ALL"] = "ALL",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    query = select(Dispute).order_by(Dispute.created_at.desc()).limit(200)
    if user.role == "CUSTOMER":
        query = query.join(Customer, Customer.id == Dispute.customer_id).where(Customer.user_id == user.id)
    if status != "ALL":
        query = query.where(Dispute.status == status)
    return [_out(db, d) for d in db.scalars(query)]


@router.get("/{dispute_id}", response_model=DisputeOut)
def get_dispute(dispute_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _out(db, _load(db, dispute_id, user), with_events=True)


@router.post("/{dispute_id}/comments", response_model=DisputeOut)
def comment(dispute_id: uuid.UUID, body: DisputeCommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    dispute = _load(db, dispute_id, user)
    if dispute.status.startswith("RESOLVED"):
        raise DomainError(409, "DISPUTE_CLOSED", "This dispute is already resolved")
    _event(db, dispute, user, "COMMENT", body.message)
    dispute.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(dispute)
    return _out(db, dispute, with_events=True)


@router.post("/{dispute_id}/assign", response_model=DisputeOut)
def assign_to_me(dispute_id: uuid.UUID, staff: User = Depends(require_staff), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    dispute = _load(db, dispute_id, staff)
    if dispute.status.startswith("RESOLVED"):
        raise DomainError(409, "DISPUTE_CLOSED", "This dispute is already resolved")
    dispute.assigned_staff_id = staff.id
    dispute.status = "INVESTIGATING"
    dispute.updated_at = datetime.now(UTC)
    _event(db, dispute, staff, "ASSIGNED", f"Assigned to {staff.username}; status INVESTIGATING")
    write_audit(db, staff.id, "DISPUTE_ASSIGNED", "DISPUTE", dispute.id, {}, meta)
    db.commit()
    db.refresh(dispute)
    return _out(db, dispute, with_events=True)


@router.post("/{dispute_id}/resolve", response_model=DisputeOut)
def resolve(dispute_id: uuid.UUID, body: DisputeResolveIn, staff: User = Depends(require_staff), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """Staff record the outcome. An upheld dispute is refunded by an admin correction reversal."""
    dispute = _load(db, dispute_id, staff)
    if dispute.status.startswith("RESOLVED"):
        raise DomainError(409, "DISPUTE_CLOSED", "This dispute is already resolved")
    now = datetime.now(UTC)
    dispute.status = body.outcome
    dispute.resolution_notes = body.notes
    dispute.resolved_at = now
    dispute.updated_at = now
    dispute.assigned_staff_id = dispute.assigned_staff_id or staff.id
    _event(db, dispute, staff, "RESOLVED", f"{body.outcome.replace('_', ' ').title()}: {body.notes}")
    write_audit(db, staff.id, "DISPUTE_RESOLVED", "DISPUTE", dispute.id, {"outcome": body.outcome}, meta)
    db.commit()
    db.refresh(dispute)
    return _out(db, dispute, with_events=True)
