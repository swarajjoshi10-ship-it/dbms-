import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AuditLog


class RequestMeta:
    """Client details captured for the audit trail."""

    def __init__(self, ip_address: str | None = None, user_agent: str | None = None):
        self.ip_address = ip_address
        self.user_agent = (user_agent or "")[:255] or None


def write_audit(
    db: Session,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    metadata: dict | None = None,
    meta: RequestMeta | None = None,
) -> None:
    """Add an audit row to the caller's transaction (commits or rolls back with the business change)."""
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id)[:64],
            ip_address=meta.ip_address if meta else None,
            user_agent=meta.user_agent if meta else None,
            metadata_json=metadata or {},
        )
    )


def write_audit_independent(
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: Any,
    metadata: dict | None = None,
    meta: RequestMeta | None = None,
) -> None:
    """Write an audit row in its own transaction, so it survives a rollback of the business work (BR12)."""
    with SessionLocal() as db:
        write_audit(db, actor_user_id, action, entity_type, entity_id, metadata, meta)
        db.commit()
