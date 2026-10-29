import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.audit import RequestMeta, write_audit
from app.db import get_db
from app.deps import request_meta, require_staff
from app.errors import DomainError
from app.ml import model as ml
from app.models import Account, FraudPrediction, GraphFinding, InvestigationNote, SimulationRun, TransferRequest, User
from app.schemas import (
    AlertDetailOut, AlertOut, FindingStatusIn, GraphFindingOut, LabRunIn, LabRunOut, NoteIn, NoteOut, ReviewIn,
)
from app.services import graph

router = APIRouter(prefix="/api", tags=["fraud"])

# Allowed staff transitions of an alert (BR14). Scores themselves are never edited.
TRANSITIONS = {
    "PENDING": {"CLEARED", "CONFIRMED_FRAUD", "ESCALATED"},
    "ESCALATED": {"CLEARED", "CONFIRMED_FRAUD"},
}

Src = aliased(Account)
Dst = aliased(Account)
Sender = aliased(User)
Reviewer = aliased(User)


def _alert_query():
    return (
        select(FraudPrediction, TransferRequest, Src.account_number, Dst.account_number, Sender.username, Reviewer.username)
        .join(TransferRequest, TransferRequest.id == FraudPrediction.transfer_request_id)
        .join(Src, Src.id == TransferRequest.source_account_id)
        .join(Dst, Dst.id == TransferRequest.destination_account_id)
        .join(Sender, Sender.id == TransferRequest.source_user_id)
        .outerjoin(Reviewer, Reviewer.id == FraudPrediction.reviewed_by_user_id)
    )


def _alert_out(row) -> dict:
    p, t, src, dst, sender, reviewer = row
    return dict(
        id=p.id, transfer_request_id=t.id, model_version=p.model_version, risk_score=p.risk_score, decision=p.decision,
        rule_flags=p.rule_flags, feature_snapshot=p.feature_snapshot, explanation=p.explanation,
        review_status=p.review_status, reviewed_by=reviewer, review_notes=p.review_notes, reviewed_at=p.reviewed_at,
        created_at=p.created_at, amount=t.amount, transfer_status=t.status, source_account_number=src,
        destination_account_number=dst, sender_username=sender,
    )


@router.get("/fraud/alerts", response_model=list[AlertOut])
def list_alerts(
    review_status: Literal["PENDING", "CLEARED", "CONFIRMED_FRAUD", "ESCALATED", "ALL"] = "PENDING",
    min_score: Decimal = Query(Decimal("0.40"), ge=0, le=1),
    limit: int = Query(100, ge=1, le=500),
    _: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    """FR9 triage queue — served by the partial index idx_fraud_pending_queue."""
    query = _alert_query().where(FraudPrediction.risk_score >= min_score)
    if review_status != "ALL":
        query = query.where(FraudPrediction.review_status == review_status)
    query = query.order_by(FraudPrediction.risk_score.desc(), FraudPrediction.created_at.desc()).limit(limit)
    return [AlertOut(**_alert_out(r)) for r in db.execute(query)]


def _alert_detail(db: Session, alert_id: uuid.UUID) -> AlertDetailOut:
    row = db.execute(_alert_query().where(FraudPrediction.id == alert_id)).one_or_none()
    if row is None:
        raise DomainError(404, "ALERT_NOT_FOUND", "Alert not found")
    notes = db.execute(
        select(InvestigationNote, User.username)
        .join(User, User.id == InvestigationNote.author_user_id)
        .where(InvestigationNote.fraud_prediction_id == alert_id)
        .order_by(InvestigationNote.created_at)
    )
    return AlertDetailOut(
        **_alert_out(row),
        notes=[NoteOut(id=n.id, author=author, note=n.note, created_at=n.created_at) for n, author in notes],
    )


@router.get("/fraud/alerts/{alert_id}", response_model=AlertDetailOut)
def get_alert(alert_id: uuid.UUID, _: User = Depends(require_staff), db: Session = Depends(get_db)):
    return _alert_detail(db, alert_id)


@router.post("/fraud/alerts/{alert_id}/review", response_model=AlertDetailOut)
def review_alert(
    alert_id: uuid.UUID, body: ReviewIn, staff: User = Depends(require_staff),
    db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta),
):
    """FR10: clear / confirm / escalate with mandatory notes. Only staff change an alert's status."""
    prediction = db.scalar(select(FraudPrediction).where(FraudPrediction.id == alert_id).with_for_update(key_share=True))  # FOR NO KEY UPDATE
    if prediction is None:
        raise DomainError(404, "ALERT_NOT_FOUND", "Alert not found")
    allowed = TRANSITIONS.get(prediction.review_status, set())
    if body.review_status not in allowed:
        raise DomainError(409, "INVALID_TRANSITION", f"An alert in {prediction.review_status} cannot move to {body.review_status}")
    previous = prediction.review_status
    prediction.review_status = body.review_status
    prediction.review_notes = body.notes
    prediction.reviewed_by_user_id = staff.id
    prediction.reviewed_at = datetime.now(UTC)
    db.add(InvestigationNote(fraud_prediction_id=prediction.id, author_user_id=staff.id, note=f"[{body.review_status}] {body.notes}"))
    write_audit(db, staff.id, "FRAUD_ALERT_REVIEWED", "FRAUD_PREDICTION", prediction.id,
                {"from": previous, "to": body.review_status}, meta)
    db.commit()
    return _alert_detail(db, alert_id)


@router.post("/fraud/alerts/{alert_id}/notes", response_model=NoteOut, status_code=201)
def add_note(alert_id: uuid.UUID, body: NoteIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    if db.get(FraudPrediction, alert_id) is None:
        raise DomainError(404, "ALERT_NOT_FOUND", "Alert not found")
    note = InvestigationNote(fraud_prediction_id=alert_id, author_user_id=staff.id, note=body.note)
    db.add(note)
    db.commit()
    return NoteOut(id=note.id, author=staff.username, note=note.note, created_at=note.created_at)


# ---------- Fraud Lab ----------
@router.post("/fraud/lab/runs", response_model=LabRunOut, status_code=201)
def run_lab(body: LabRunIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Evaluate the model on a fresh synthetic population and keep the metrics."""
    seed = body.seed if body.seed is not None else int(datetime.now(UTC).timestamp())
    metrics = ml.evaluate(body.n_samples, body.fraud_rate, seed)
    q = lambda v: Decimal(str(v)).quantize(Decimal("0.0001"))  # noqa: E731
    run = SimulationRun(
        run_by_user_id=staff.id, model_version=ml.MODEL_VERSION,
        scenario={"fraud_rate": body.fraud_rate, "seed": seed, "threshold": 0.5},
        n_samples=body.n_samples, accuracy=q(metrics["accuracy"]), precision_score=q(metrics["precision"]),
        recall_score=q(metrics["recall"]), f1_score=q(metrics["f1"]), confusion=metrics["confusion"],
    )
    db.add(run)
    db.commit()
    return run


@router.get("/fraud/lab/runs", response_model=list[LabRunOut])
def list_lab_runs(_: User = Depends(require_staff), db: Session = Depends(get_db)):
    return db.scalars(select(SimulationRun).order_by(SimulationRun.created_at.desc()).limit(50)).all()


# ---------- graph findings ----------
def _finding_out(db: Session, f: GraphFinding) -> GraphFindingOut:
    ids = [uuid.UUID(i) for i in f.involved_account_ids]
    numbers = dict(db.execute(select(Account.id, Account.account_number).where(Account.id.in_(ids))).all()) if ids else {}
    return GraphFindingOut(
        id=f.id, finding_type=f.finding_type, primary_account_number=f.primary_account.account_number,
        involved_account_numbers=[numbers.get(i, str(i)) for i in ids], total_amount=f.total_amount,
        severity=f.severity, details=f.details, status=f.status, created_at=f.created_at,
    )


@router.post("/graph/scan", response_model=list[GraphFindingOut])
def scan_graph(staff: User = Depends(require_staff), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    created = graph.scan(db)
    write_audit(db, staff.id, "GRAPH_SCAN", "GRAPH", "payee_edges", {"new_findings": len(created)}, meta)
    db.commit()
    return [_finding_out(db, f) for f in created]


@router.get("/graph/findings", response_model=list[GraphFindingOut])
def list_findings(
    status: Literal["OPEN", "DISMISSED", "CONFIRMED", "ALL"] = "OPEN",
    _: User = Depends(require_staff), db: Session = Depends(get_db),
):
    query = select(GraphFinding).order_by(GraphFinding.created_at.desc()).limit(200)
    if status != "ALL":
        query = query.where(GraphFinding.status == status)
    return [_finding_out(db, f) for f in db.scalars(query)]


@router.patch("/graph/findings/{finding_id}", response_model=GraphFindingOut)
def update_finding(
    finding_id: uuid.UUID, body: FindingStatusIn, staff: User = Depends(require_staff),
    db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta),
):
    finding = db.get(GraphFinding, finding_id)
    if finding is None:
        raise DomainError(404, "FINDING_NOT_FOUND", "Finding not found")
    finding.status = body.status
    write_audit(db, staff.id, "GRAPH_FINDING_UPDATED", "GRAPH_FINDING", finding.id, {"status": body.status}, meta)
    db.commit()
    return _finding_out(db, finding)
