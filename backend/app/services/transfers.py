"""Customer transfers: idempotency, posting through sp_transfer_funds, durable failures, reversals."""
import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit, write_audit_independent
from app.db import SessionLocal
from app.errors import DomainError, domain_error_from_db, pg_error_parts
from app.models import Account, TransferRequest, User
from app.schemas import PredictionBrief, TransferIn, TransferOut
from app.services import fraud

# Failures that still have two valid, distinct accounts, so a FAILED transfer row can be stored.
RECORDABLE_FAILURES = {"FLOWN", "FLSTS", "FLNSF", "FLINT"}


def request_hash(payload: TransferIn) -> str:
    """SHA-256 of the canonical payload; a reused idempotency key must carry the same payload."""
    canonical = {
        "source_account_id": str(payload.source_account_id),
        "destination_account_number": payload.destination_account_number,
        "amount": str(payload.amount.quantize(Decimal("0.01"))),
        "description": payload.description or "",
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _replay(existing: TransferRequest, req_hash: str) -> TransferRequest:
    if existing.request_hash != req_hash:
        raise DomainError(
            409, "IDEMPOTENCY_KEY_REUSED", "This idempotency key was already used for a different transfer",
            {"transfer_id": str(existing.id)},
        )
    return existing


def _find_by_key(db: Session, user: User, key: str) -> TransferRequest | None:
    return db.scalar(
        select(TransferRequest).where(TransferRequest.source_user_id == user.id, TransferRequest.idempotency_key == key)
    )


def _record_failure(user, key, req_hash, src_id, dst_id, amount, sqlstate, message, meta) -> uuid.UUID | None:
    """Store the FAILED request and its audit row in a transaction of their own (BR12)."""
    transfer_id = None
    with SessionLocal() as db:
        if sqlstate in RECORDABLE_FAILURES and dst_id is not None and src_id != dst_id:
            failed = TransferRequest(
                idempotency_key=key, source_user_id=user.id, request_hash=req_hash, source_account_id=src_id,
                destination_account_id=dst_id, amount=amount, status="FAILED", failure_reason=message,
            )
            db.add(failed)
            db.flush()
            transfer_id = failed.id
        write_audit(
            db, user.id, "TRANSFER_FAILED", "TRANSFER", transfer_id or key,
            {"reason": message, "sqlstate": sqlstate, "amount": str(amount),
             "source_account_id": str(src_id), "destination_account_id": str(dst_id) if dst_id else None},
            meta,
        )
        db.commit()
    return transfer_id


def create_transfer(db: Session, user: User, key: str, payload: TransferIn, meta: RequestMeta) -> tuple[TransferRequest, bool]:
    """Returns (transfer, replayed). Raises DomainError for refused transfers (after recording them)."""
    req_hash = request_hash(payload)

    existing = _find_by_key(db, user, key)
    if existing:
        return _replay(existing, req_hash), True

    destination = db.scalar(select(Account).where(Account.account_number == payload.destination_account_number))
    dst_id = destination.id if destination else None
    try:
        if destination is None:
            raise DomainError(404, "ACCOUNT_NOT_FOUND", "Destination account not found")
        transfer_id = db.execute(
            text("SELECT sp_transfer_funds(:user, :key, :hash, :src, :dst, :amount, :desc)"),
            {"user": user.id, "key": key, "hash": req_hash, "src": payload.source_account_id,
             "dst": dst_id, "amount": payload.amount, "desc": payload.description},
        ).scalar_one()
        write_audit(
            db, user.id, "TRANSFER_POSTED", "TRANSFER", transfer_id,
            {"amount": str(payload.amount), "source_account_id": str(payload.source_account_id),
             "destination_account_number": payload.destination_account_number},
            meta,
        )
        db.commit()
    except DomainError as exc:
        db.rollback()
        write_audit_independent(user.id, "TRANSFER_FAILED", "TRANSFER", key, {"reason": exc.message}, meta)
        raise
    except DBAPIError as exc:
        db.rollback()
        sqlstate, message = pg_error_parts(exc)
        if sqlstate == "23505" and "uq_transfers_user_idempotency" in str(exc.orig):
            # A concurrent retry with the same key won the race: replay its result.
            return _replay(_find_by_key(db, user, key), req_hash), True
        mapped = domain_error_from_db(exc)
        if mapped is None:
            raise
        failed_id = _record_failure(user, key, req_hash, payload.source_account_id, dst_id, payload.amount, sqlstate, message, meta)
        if failed_id:
            mapped.extra["transfer_id"] = str(failed_id)
        raise mapped from None

    transfer = db.get(TransferRequest, transfer_id)
    fraud.score_transfer_safely(db, transfer)
    return transfer, False


def reverse_transfer(db: Session, admin: User, transfer_id: uuid.UUID, reason: str, meta: RequestMeta) -> uuid.UUID:
    """Admin correction (BR13): a new CORRECTION_REVERSAL posting, never an edit."""
    try:
        txn_id = db.execute(
            text("SELECT sp_reverse_transfer(:tid, :admin, :reason)"),
            {"tid": transfer_id, "admin": admin.id, "reason": reason},
        ).scalar_one()
        write_audit(db, admin.id, "TRANSFER_REVERSED", "TRANSFER", transfer_id, {"reason": reason, "reversal_transaction_id": str(txn_id)}, meta)
        db.commit()
        return txn_id
    except DBAPIError as exc:
        db.rollback()
        mapped = domain_error_from_db(exc)
        if mapped is None:
            raise
        write_audit_independent(admin.id, "TRANSFER_REVERSAL_FAILED", "TRANSFER", transfer_id, {"reason": mapped.message}, meta)
        raise mapped from None


def to_out(db: Session, transfer: TransferRequest, replayed: bool = False, include_prediction: bool = True) -> TransferOut:
    src = db.get(Account, transfer.source_account_id)
    dst = db.get(Account, transfer.destination_account_id)
    prediction = transfer.prediction if include_prediction else None
    return TransferOut(
        id=transfer.id,
        idempotency_key=transfer.idempotency_key,
        status=transfer.status,
        amount=transfer.amount,
        currency=transfer.currency,
        source_account_id=src.id,
        source_account_number=src.account_number,
        destination_account_id=dst.id,
        destination_account_number=dst.account_number,
        failure_reason=transfer.failure_reason,
        created_at=transfer.created_at,
        posted_at=transfer.posted_at,
        replayed=replayed,
        prediction=PredictionBrief.model_validate(prediction) if prediction else None,
    )
