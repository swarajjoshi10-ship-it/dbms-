# FinLedger-AI: Review 2 Code Reference Guide
**Course:** BCSE302P Database Systems | **Evaluation:** Review 2 (10 Marks)

This document contains the exact code snippets for every part of the demonstration. Keep this file open in your editor or split-screen so you can reference or display the code effortlessly without hunting across the repository.

---

## Part 1: Schema Constraints & Domain Rules (BR1–BR7)
**Source File:** `backend/alembic/versions/aa388336f576_core_schema.py` and `backend/app/models.py`

```python
# Balance non-negativity constraint (No overdrafts at DB level)
CheckConstraint("cached_balance >= 0", name="chk_accounts_non_negative_balance")

# Currency domain restriction
CheckConstraint("currency = 'INR'", name="chk_accounts_currency_inr")

# Role integrity check
CheckConstraint("role IN ('CUSTOMER', 'STAFF', 'ADMIN')", name="chk_users_role_valid")

# Positive transfer amount constraint
CheckConstraint("amount > 0", name="chk_transfers_amount_positive")

# Ledger entry classification
CheckConstraint("entry_type IN ('DEBIT', 'CREDIT')", name="chk_ledger_entry_type")
```

---

## Part 2: Deadlock-Free Atomic Transfer Stored Procedure (BR10 & Procedures)
**Source File:** `backend/alembic/versions/d9e4a1b7c6f3_procedures_and_views.py` (Lines 45–95)

```sql
CREATE OR REPLACE FUNCTION sp_transfer_funds(
    p_source_user_id        UUID,
    p_idempotency_key       VARCHAR(64),
    p_request_hash          VARCHAR(64),
    p_source_account_id     UUID,
    p_destination_account_id UUID,
    p_amount                NUMERIC(15,2),
    p_description           TEXT
) RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE
    v_src accounts%ROWTYPE;
    v_dst accounts%ROWTYPE;
    v_transfer_id UUID := gen_random_uuid();
    v_txn_id      UUID := gen_random_uuid();
BEGIN
    -- 1. DEADLOCK PREVENTION: Global Lock Hierarchy (Order by UUID)
    IF p_source_account_id < p_destination_account_id THEN
        SELECT * INTO v_src FROM accounts WHERE id = p_source_account_id FOR UPDATE;
        SELECT * INTO v_dst FROM accounts WHERE id = p_destination_account_id FOR UPDATE;
    ELSE
        SELECT * INTO v_dst FROM accounts WHERE id = p_destination_account_id FOR UPDATE;
        SELECT * INTO v_src FROM accounts WHERE id = p_source_account_id FOR UPDATE;
    END IF;

    -- 2. BUSINESS VALIDATIONS
    IF v_src.status <> 'ACTIVE' THEN
        RAISE EXCEPTION 'Source account % is %', v_src.account_number, v_src.status USING ERRCODE = 'check_violation';
    END IF;

    IF v_src.cached_balance < p_amount THEN
        RAISE EXCEPTION 'Insufficient funds: available %, requested %', v_src.cached_balance, p_amount USING ERRCODE = 'check_violation';
    END IF;

    -- 3. ATOMIC DOUBLE-ENTRY POSTING
    INSERT INTO ledger_transactions (id, transaction_type, description)
    VALUES (v_txn_id, 'CUSTOMER_TRANSFER', p_description);

    INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num)
    VALUES 
        (v_txn_id, v_src.id, 'DEBIT',  p_amount, 1),
        (v_txn_id, v_dst.id, 'CREDIT', p_amount, 2);

    -- 4. CACHED BALANCE UPDATE
    UPDATE accounts SET cached_balance = cached_balance - p_amount WHERE id = v_src.id;
    UPDATE accounts SET cached_balance = cached_balance + p_amount WHERE id = v_dst.id;

    RETURN v_transfer_id;
END;
$$;
```

---

## Part 3: Running Balance Statement View with SQL Window Functions (BR15 & Views)
**Source File:** `backend/alembic/versions/d9e4a1b7c6f3_procedures_and_views.py` (Lines 190–215)

```sql
CREATE OR REPLACE VIEW v_account_statement AS
SELECT 
    e.account_id,
    t.id AS transaction_id,
    t.created_at,
    e.sequence_num,
    t.transaction_type,
    t.description,
    e.entry_type,
    e.amount,
    -- DYNAMIC PASSBOOK BALANCE COMPUTED ON THE FLY:
    SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END)
        OVER (
            PARTITION BY e.account_id 
            ORDER BY t.created_at, e.sequence_num
        ) AS running_balance,
    cp_acc.account_number AS counterparty
FROM ledger_entries e
JOIN ledger_transactions t ON t.id = e.transaction_id
LEFT JOIN ledger_entries cp ON cp.transaction_id = e.transaction_id AND cp.id <> e.id
LEFT JOIN accounts cp_acc ON cp_acc.id = cp.account_id;
```

---

## Part 4: Deferred Double-Entry Zero-Sum Trigger (BR8 & Triggers)
**Source File:** `backend/alembic/versions/b7c1e2d40a11_integrity_triggers.py` (Lines 63–86)

```sql
CREATE OR REPLACE FUNCTION verify_transaction_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_delta NUMERIC(17,2);
BEGIN
    -- Verify Debits - Credits == 0 for the entire transaction batch
    SELECT COALESCE(SUM(CASE WHEN entry_type = 'DEBIT' THEN amount ELSE -amount END), 0)
      INTO v_delta
      FROM ledger_entries
     WHERE transaction_id = NEW.transaction_id;

    IF v_delta <> 0 THEN
        RAISE EXCEPTION 'Ledger transaction % is unbalanced: delta is %',
            NEW.transaction_id, v_delta USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- DEFERRED CONSTRAINT TRIGGER: Waits until COMMIT
CREATE CONSTRAINT TRIGGER trg_verify_ledger_balance
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION verify_transaction_balance();
```

---

## Part 5: Append-Only Immutability & Anti-Truncate Triggers (BR9 & Triggers)
**Source File:** `backend/alembic/versions/b7c1e2d40a11_integrity_triggers.py` (Lines 18–57)

```sql
-- Block all row-level edits and deletes
CREATE OR REPLACE FUNCTION prevent_record_modification() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Table % is strictly append-only; updates and deletes are prohibited', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

CREATE TRIGGER trg_immutable_audit_logs
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_record_modification();

-- Block statement-level TRUNCATE commands
CREATE OR REPLACE FUNCTION prevent_append_only_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF current_setting('finledger.allow_truncate', true) = 'on' THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Table % is strictly append-only; TRUNCATE is prohibited', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER trg_no_truncate_audit_logs
    BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION prevent_append_only_truncate();
```

---

## Part 6: Idempotency Hashing & Durable Failure Logging (BR11 & BR12)
**Source File:** `backend/app/services/transfers.py` (Lines 22–60)

```python
def request_hash(payload: TransferIn) -> str:
    """SHA-256 canonical hash of transfer payload."""
    canonical = {
        "source_account_id": str(payload.source_account_id),
        "destination_account_number": payload.destination_account_number,
        "amount": str(payload.amount.quantize(Decimal("0.01"))),
        "description": payload.description or "",
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()

def _record_failure(user, key, req_hash, src_id, dst_id, amount, sqlstate, message, meta):
    """Saves FAILED transfer in an independent transaction so rejection leaves evidence."""
    with SessionLocal() as db:
        failed = TransferRequest(
            idempotency_key=key,
            source_user_id=user.id,
            request_hash=req_hash,
            source_account_id=src_id,
            destination_account_id=dst_id,
            amount=amount,
            status="FAILED",
            failure_reason=message,
        )
        db.add(failed)
        db.commit()
```

---

## Part 7: Graph Scan (Recursive CTE)
**Source File:** `backend/app/services/graph.py` (Lines 25–60)

```sql
WITH RECURSIVE transfer_graph AS (
    -- Anchor member
    SELECT source_account_id, destination_account_id, 
           ARRAY[source_account_id] AS path, 1 AS depth
      FROM transfer_requests
     WHERE status = 'POSTED'
    
    UNION ALL
    
    -- Recursive member detecting cycles
    SELECT g.source_account_id, t.destination_account_id, 
           path || t.destination_account_id, g.depth + 1
      FROM transfer_graph g
      JOIN transfer_requests t ON t.source_account_id = g.destination_account_id
     WHERE g.depth < 5
       AND NOT t.destination_account_id = ANY(g.path)
)
SELECT * FROM transfer_graph WHERE destination_account_id = source_account_id;
```

---

## Part 8: Non-Destructive Compensating Reversal Procedure (BR13 & Procedures)
**Source File:** `backend/alembic/versions/d9e4a1b7c6f3_procedures_and_views.py` (Lines 130–165)

```sql
CREATE OR REPLACE FUNCTION sp_reverse_transfer(
    p_transfer_id   UUID,
    p_admin_user_id UUID,
    p_reason        TEXT
) RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE
    v_orig transfer_requests%ROWTYPE;
    v_rev_txn_id UUID := gen_random_uuid();
BEGIN
    SELECT * INTO v_orig FROM transfer_requests WHERE id = p_transfer_id FOR UPDATE;

    IF v_orig.status <> 'POSTED' THEN
        RAISE EXCEPTION 'Only POSTED transfers can be reversed (status is %)', v_orig.status;
    END IF;

    -- Invert legs: Credit original sender, Debit original receiver
    INSERT INTO ledger_transactions (id, transaction_type, description)
    VALUES (v_rev_txn_id, 'TRANSFER_REVERSAL', p_reason);

    INSERT INTO ledger_entries (transaction_id, account_id, entry_type, amount, sequence_num)
    VALUES 
        (v_rev_txn_id, v_orig.destination_account_id, 'DEBIT',  v_orig.amount, 1),
        (v_rev_txn_id, v_orig.source_account_id,      'CREDIT', v_orig.amount, 2);

    UPDATE accounts SET cached_balance = cached_balance - v_orig.amount WHERE id = v_orig.destination_account_id;
    UPDATE accounts SET cached_balance = cached_balance + v_orig.amount WHERE id = v_orig.source_account_id;

    UPDATE transfer_requests SET status = 'REVERSED' WHERE id = p_transfer_id;
    RETURN v_rev_txn_id;
END;
$$;
```

---

## Part 9: Advanced Joins & Subqueries Showcase
**Source File:** `sql/review2.sql` (Lines 34–88)

```sql
-- LEFT JOIN preserving internal clearing accounts
SELECT a.account_number, a.account_type, COALESCE(c.full_name, '(bank internal)') AS owner
  FROM accounts a 
  LEFT JOIN customers c ON c.id = a.customer_id;

-- SELF JOIN pairing DEBIT and CREDIT legs
SELECT t.transaction_type, d_acc.account_number AS debited, c_acc.account_number AS credited, d.amount
  FROM ledger_entries d
  JOIN ledger_entries c ON c.transaction_id = d.transaction_id AND c.entry_type = 'CREDIT'
  JOIN ledger_transactions t ON t.id = d.transaction_id
  JOIN accounts d_acc ON d_acc.id = d.account_id
  JOIN accounts c_acc ON c_acc.id = c.account_id
 WHERE d.entry_type = 'DEBIT';

-- Correlated Subquery: Largest account per customer
SELECT c.full_name, a.account_number, a.cached_balance
  FROM customers c JOIN accounts a ON a.customer_id = c.id
 WHERE a.cached_balance = (SELECT MAX(a2.cached_balance) FROM accounts a2 WHERE a2.customer_id = c.id);

-- NOT EXISTS: Customers with zero transfers
SELECT c.full_name FROM customers c
 WHERE NOT EXISTS (SELECT 1 FROM transfer_requests t WHERE t.source_user_id = c.user_id);
```

---

## Part 10: Functions & Explicit PL/pgSQL Cursor
**Source File:** `sql/review2.sql` (Lines 119–162)

```sql
-- SQL Masking Function (PCI-DSS)
CREATE OR REPLACE FUNCTION fn_mask_account(p_number VARCHAR) RETURNS VARCHAR
LANGUAGE sql IMMUTABLE AS $$
    SELECT LPAD(RIGHT(p_number, 4), LENGTH(p_number), 'X')
$$;

-- Explicit Cursor calculating quarterly compounded maturity
DO $$
DECLARE
    cur_products CURSOR FOR
        SELECT code, min_amount, annual_yield_rate, term_months FROM financial_products WHERE is_active;
    rec RECORD;
    v_maturity NUMERIC(15,2);
BEGIN
    OPEN cur_products;
    LOOP
        FETCH cur_products INTO rec;
        EXIT WHEN NOT FOUND;
        v_maturity := ROUND(rec.min_amount * POWER(1 + rec.annual_yield_rate / 400.0, rec.term_months / 3.0), 2);
        RAISE NOTICE '% : % invested -> Maturity: %', rec.code, rec.min_amount, v_maturity;
    END LOOP;
    CLOSE cur_products;
END;
$$;
```
