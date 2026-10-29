"""Advisory fraud scoring (BR14).

A score is written AFTER the transfer has committed. The model never blocks, freezes or
reverses anything: it stores a risk score, rule flags, the feature snapshot and a plain-language
explanation, and staff decide what happens next.
"""
import logging
import uuid
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml import model as ml
from app.models import FraudPrediction, TransferRequest

log = logging.getLogger(__name__)

RULES_ONLY_VERSION = "rules-v1"

# (flag, weight, description) — weights add up to the rule score, capped at 1.
RULES: dict[str, tuple[float, str]] = {
    "HIGH_AMOUNT": (0.25, "amount is ₹2,00,000 or more"),
    "AMOUNT_SPIKE": (0.25, "amount is at least 5× the sender's average transfer"),
    "NEW_PAYEE_LARGE": (0.30, "first transfer to this payee and ₹50,000 or more"),
    "BALANCE_DRAIN": (0.30, "empties 90% or more of the source balance"),
    "VELOCITY": (0.30, "5 or more transfers by this sender in the last hour"),
    "ODD_HOUR": (0.15, "₹20,000 or more sent between midnight and 5 a.m. IST"),
    "NEW_ACCOUNT": (0.20, "source account is under 7 days old and amount is ₹25,000 or more"),
    "MULE_FAN_IN": (0.35, "destination received money from 4 or more different accounts in 24 hours"),
}

FEATURE_SQL = text(
    """
    WITH t AS (
        SELECT * FROM transfer_requests WHERE id = :tid
    ), prior AS (
        SELECT COUNT(*) AS n, AVG(p.amount) AS avg_amount
          FROM transfer_requests p, t
         WHERE p.source_user_id = t.source_user_id
           AND p.status IN ('POSTED', 'REVERSED')
           AND p.created_at < t.created_at
    )
    SELECT t.amount,
           prior.n                                                       AS prior_count,
           COALESCE(t.amount / NULLIF(prior.avg_amount, 0), 1.0)         AS amount_to_avg_ratio,
           EXTRACT(HOUR FROM (t.created_at AT TIME ZONE 'UTC') + INTERVAL '5 hours 30 minutes') AS hour_of_day,  -- IST (UTC+5:30, no DST)
           CASE WHEN EXISTS (
                SELECT 1 FROM transfer_requests q
                 WHERE q.source_account_id = t.source_account_id
                   AND q.destination_account_id = t.destination_account_id
                   AND q.status IN ('POSTED', 'REVERSED')
                   AND q.created_at < t.created_at) THEN 0 ELSE 1 END AS is_new_payee,
           EXTRACT(EPOCH FROM (t.created_at - a.created_at)) / 86400.0   AS sender_account_age_days,
           (SELECT COUNT(*) FROM transfer_requests v
             WHERE v.source_user_id = t.source_user_id
               AND v.status IN ('POSTED', 'REVERSED')
               AND v.created_at BETWEEN t.created_at - INTERVAL '1 hour' AND t.created_at) AS transfers_last_hour,
           (SELECT s.running_balance + t.amount FROM v_account_statement s
             WHERE s.account_id = t.source_account_id
               AND s.transfer_request_id = t.id AND s.entry_type = 'DEBIT')  AS balance_before,
           (SELECT COUNT(DISTINCT f.source_account_id) FROM transfer_requests f
             WHERE f.destination_account_id = t.destination_account_id
               AND f.status IN ('POSTED', 'REVERSED')
               AND f.created_at BETWEEN t.created_at - INTERVAL '24 hours' AND t.created_at) AS dest_distinct_senders_24h
      FROM t, prior, accounts a
     WHERE a.id = t.source_account_id
    """
)


def compute_features(db: Session, transfer_id: uuid.UUID) -> tuple[dict, int]:
    row = db.execute(FEATURE_SQL, {"tid": transfer_id}).mappings().one()
    amount = Decimal(row["amount"])
    balance_before = Decimal(row["balance_before"] or amount)
    features = {
        "amount": float(amount),
        "amount_to_avg_ratio": round(float(row["amount_to_avg_ratio"]), 4),
        "hour_of_day": int(row["hour_of_day"]),
        "is_new_payee": int(row["is_new_payee"]),
        "sender_account_age_days": round(float(row["sender_account_age_days"]), 2),
        "transfers_last_hour": int(row["transfers_last_hour"]),
        "balance_drain_ratio": round(float(amount / balance_before) if balance_before > 0 else 1.0, 4),
        "dest_distinct_senders_24h": int(row["dest_distinct_senders_24h"]),
    }
    return features, int(row["prior_count"])


def evaluate_rules(f: dict, prior_count: int) -> list[str]:
    flags = []
    if f["amount"] >= 200000:
        flags.append("HIGH_AMOUNT")
    if prior_count >= 3 and f["amount_to_avg_ratio"] >= 5:
        flags.append("AMOUNT_SPIKE")
    if f["is_new_payee"] and f["amount"] >= 50000:
        flags.append("NEW_PAYEE_LARGE")
    if f["balance_drain_ratio"] >= 0.9 and f["amount"] >= 10000:
        flags.append("BALANCE_DRAIN")
    if f["transfers_last_hour"] >= 5:
        flags.append("VELOCITY")
    if f["hour_of_day"] < 5 and f["amount"] >= 20000:
        flags.append("ODD_HOUR")
    if f["sender_account_age_days"] < 7 and f["amount"] >= 25000:
        flags.append("NEW_ACCOUNT")
    if f["dest_distinct_senders_24h"] >= 4:
        flags.append("MULE_FAN_IN")
    return flags


def band(score: Decimal) -> str:
    if score >= Decimal("0.70"):
        return "HIGH_RISK"
    if score >= Decimal("0.40"):
        return "MEDIUM_RISK"
    return "LOW_RISK"


def explain(score: Decimal, decision: str, flags: list[str], model_prob: float | None, version: str) -> str:
    # Truncate, never round up: 0.6950 must read 0.69, inside its MEDIUM band, not 0.70.
    shown = score.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    parts = [f"Risk score {shown} ({decision.replace('_', ' ').lower()})."]
    if flags:
        parts.append("Signals: " + "; ".join(RULES[f][1] for f in flags) + ".")
    else:
        parts.append("No rule-based signal fired.")
    if model_prob is not None:
        parts.append(f"Random Forest probability {model_prob:.2f} from the transfer's behavioural features.")
    parts.append(f"Model {version} is advisory only; a staff reviewer decides the outcome.")
    return " ".join(parts)


def score_transfer(db: Session, transfer_id: uuid.UUID) -> FraudPrediction:
    """Compute and store the advisory prediction for a POSTED transfer (idempotent)."""
    existing = db.query(FraudPrediction).filter_by(transfer_request_id=transfer_id).one_or_none()
    if existing:
        return existing

    features, prior_count = compute_features(db, transfer_id)
    flags = evaluate_rules(features, prior_count)
    rule_score = min(1.0, sum(RULES[f][0] for f in flags))

    model_prob: float | None
    try:
        model_prob = ml.predict_proba(features)
        version = ml.MODEL_VERSION
        raw = 0.6 * model_prob + 0.4 * rule_score
    except Exception:  # model unavailable: fall back to the rule baseline
        log.exception("Fraud model unavailable; using rule baseline")
        model_prob, version, raw = None, RULES_ONLY_VERSION, rule_score

    score = Decimal(str(min(max(raw, 0.0), 1.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    decision = band(score)
    prediction = FraudPrediction(
        transfer_request_id=transfer_id,
        model_version=version,
        risk_score=score,
        decision=decision,
        rule_flags=flags,
        feature_snapshot={**features, "rule_score": round(rule_score, 4), "model_probability": model_prob},
        explanation=explain(score, decision, flags, model_prob, version),
    )
    db.add(prediction)
    db.commit()
    return prediction


def score_transfer_safely(db: Session, transfer: TransferRequest) -> FraudPrediction | None:
    """Scoring must never undo or fail a committed transfer."""
    try:
        return score_transfer(db, transfer.id)
    except Exception:
        db.rollback()
        log.exception("Fraud scoring failed for transfer %s", transfer.id)
        return None
