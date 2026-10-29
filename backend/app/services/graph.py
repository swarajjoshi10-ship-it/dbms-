"""Graph-based money-flow signals over payee_edges and transfer_requests.

* CYCLE              money that returns to where it started through 3–4 hops in 7 days
                     (found with a recursive CTE over payee_edges)
* FAN_IN             one account receiving from 4+ distinct accounts in 24 hours (mule pattern)
* RAPID_PASS_THROUGH an account that forwards 80%+ of what it received within an hour
"""
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import GraphFinding

CYCLE_SQL = text(
    """
    WITH RECURSIVE walk(start_id, current_id, path, total, depth) AS (
        SELECT source_account_id, destination_account_id,
               ARRAY[source_account_id, destination_account_id], total_amount::NUMERIC, 1
          FROM payee_edges
         WHERE last_seen_at > now() - INTERVAL '7 days'
        UNION ALL
        SELECT w.start_id, e.destination_account_id, w.path || e.destination_account_id,
               w.total + e.total_amount, w.depth + 1
          FROM walk w
          JOIN payee_edges e ON e.source_account_id = w.current_id
         WHERE w.depth < 4
           AND w.current_id <> w.start_id
           AND e.last_seen_at > now() - INTERVAL '7 days'
           AND (e.destination_account_id = w.start_id OR NOT e.destination_account_id = ANY (w.path))
    )
    SELECT start_id, path, total, depth
      FROM walk
     WHERE current_id = start_id AND depth >= 3
    """
)

FAN_IN_SQL = text(
    """
    SELECT destination_account_id AS account_id,
           COUNT(DISTINCT source_account_id) AS senders,
           SUM(amount) AS total,
           ARRAY_AGG(DISTINCT source_account_id) AS sources
      FROM transfer_requests
     WHERE status IN ('POSTED', 'REVERSED') AND created_at > now() - INTERVAL '24 hours'
     GROUP BY destination_account_id
    HAVING COUNT(DISTINCT source_account_id) >= 4
    """
)

PASS_THROUGH_SQL = text(
    """
    -- One row per account: its largest incoming transfer from ANOTHER customer that was
    -- mostly sent on to other customers within the hour.
    SELECT DISTINCT ON (i.destination_account_id)
           i.destination_account_id AS account_id,
           i.amount                 AS received,
           o.sent,
           o.receivers
      FROM transfer_requests i
      JOIN accounts si ON si.id = i.source_account_id
      JOIN accounts di ON di.id = i.destination_account_id
      JOIN LATERAL (
            SELECT SUM(x.amount) AS sent, ARRAY_AGG(DISTINCT x.destination_account_id) AS receivers
              FROM transfer_requests x
              JOIN accounts dx ON dx.id = x.destination_account_id
             WHERE x.source_account_id = i.destination_account_id
               AND dx.customer_id IS DISTINCT FROM di.customer_id
               AND x.status IN ('POSTED', 'REVERSED')
               AND x.created_at BETWEEN i.created_at AND i.created_at + INTERVAL '1 hour'
      ) o ON TRUE
     WHERE i.status IN ('POSTED', 'REVERSED')
       AND si.customer_id IS DISTINCT FROM di.customer_id
       AND i.created_at > now() - INTERVAL '24 hours'
       AND i.amount >= 10000
       AND o.sent >= 0.8 * i.amount
     ORDER BY i.destination_account_id, i.amount DESC
    """
)


def _already_open(db: Session, finding_type: str, account_id, involved: list[str]) -> bool:
    return db.scalar(
        select(GraphFinding.id).where(
            GraphFinding.finding_type == finding_type,
            GraphFinding.primary_account_id == account_id,
            GraphFinding.status == "OPEN",
            GraphFinding.involved_account_ids == involved,
        )
    ) is not None


def scan(db: Session) -> list[GraphFinding]:
    created: list[GraphFinding] = []
    seen: set[tuple] = set()

    def add(finding_type, account_id, involved, total, severity, details):
        involved = sorted(str(a) for a in involved)
        key = (finding_type, str(account_id), tuple(involved))
        if key in seen or _already_open(db, finding_type, account_id, involved):
            return
        seen.add(key)
        finding = GraphFinding(
            finding_type=finding_type, primary_account_id=account_id, involved_account_ids=involved,
            total_amount=Decimal(total).quantize(Decimal("0.01")), severity=severity, details=details,
        )
        db.add(finding)
        created.append(finding)

    seen_cycles: set[frozenset] = set()
    for row in db.execute(CYCLE_SQL).mappings():
        nodes = row["path"][:-1]
        key = frozenset(nodes)
        # The same cycle is found once per starting node; keep one rotation.
        if key in seen_cycles:
            continue
        seen_cycles.add(key)
        start = min(nodes, key=str)
        add("CYCLE", start, nodes, row["total"], "HIGH", {"hops": row["depth"], "path": [str(n) for n in row["path"]]})

    for row in db.execute(FAN_IN_SQL).mappings():
        severity = "HIGH" if row["senders"] >= 8 else "MEDIUM"
        add("FAN_IN", row["account_id"], row["sources"], row["total"], severity, {"distinct_senders_24h": row["senders"]})

    for row in db.execute(PASS_THROUGH_SQL).mappings():
        add(
            "RAPID_PASS_THROUGH", row["account_id"], row["receivers"], row["sent"], "MEDIUM",
            {"received": str(row["received"]), "forwarded_within_1h": str(row["sent"])},
        )

    db.commit()
    return created
