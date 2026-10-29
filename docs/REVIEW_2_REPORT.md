# FinLedger-AI: Review 2 — Advanced SQL & PL/SQL Implementation
**Course:** BCSE302P Database Systems  
**Evaluation:** Review 2 (10 Marks)  
**Project:** FinLedger-AI — Auditable Double-Entry Core Banking with Explainable AI Fraud Detection  

---

## 📑 Executive Summary & Rubric Alignment

This document details the complete design, implementation, and empirical verification for **Review 2 (Advanced SQL & PL/SQL Implementation: 10 Marks)**. 

All SQL scripts, procedural routines, and triggers documented herein are fully implemented and verifiable via the reproducible script:
[`sql/review2.sql`](../sql/review2.sql), executed against the PostgreSQL 16 engine on database `finledger_review`.

| Rubric Component | Database Artifacts Implemented | Key Engineering Justification |
|---|---|---|
| **1. Subqueries** | Scalar, Correlated, `NOT EXISTS`, `IN` | Dynamic aggregate comparisons, record-level partitioning, activity filtering. |
| **2. Joins** | INNER (4-table), LEFT OUTER, SELF JOIN, RIGHT OUTER | Transaction flow resolution, unassigned clearing accounts, debit/credit leg pairing. |
| **3. Views** | `v_customer_summary`, `v_account_statement`, `v_account_reconciliation` | Abstraction, real-time window function running balances, zero-drift verification. |
| **4. Procedures** | `sp_transfer_funds`, `sp_reverse_transfer` | ACID atomicity, deadlock-free lock sorting, idempotency, compensating reversals. |
| **5. Functions (UDFs)**| `fn_mask_account`, `fn_customer_net_worth` | PCI-DSS data masking, parameterized customer portfolio valuation. |
| **6. Cursors** | Explicit PL/pgSQL cursor on `financial_products` | Iterative financial batch processing with quarterly compounding calculations. |
| **7. Triggers** | Row-level immutability, statement anti-truncate, deferred double-entry verification | Enforcing append-only auditability and mathematical zero-sum ledger consistency. |

---

## 1. Subqueries

In financial ledgers, subqueries prevent hardcoded thresholds by comparing individual account and customer metrics against dynamic dataset statistics.

### 1.1 Scalar Subquery (Dynamic Threshold Filtering)
Find accounts holding balances strictly higher than the overall average customer balance (excluding internal clearing accounts):

```sql
SELECT account_number, cached_balance
  FROM accounts
 WHERE account_type <> 'INTERNAL_CLEARING'
   AND cached_balance > (
       SELECT AVG(cached_balance) 
         FROM accounts 
        WHERE account_type <> 'INTERNAL_CLEARING'
   )
 ORDER BY cached_balance DESC;
```
* **Execution Output:**
  ```text
    account_number  | cached_balance 
  ------------------+----------------
   INR-CUR-9F0D3A71 |      310000.00
   INR-SAV-81A4C0E2 |      233000.00
  (2 rows)
  ```

---

### 1.2 Correlated Subquery (Per-Customer Extremum)
Identify the largest account belonging to each specific customer, dynamically correlated on `c.id`:

```sql
SELECT c.full_name, a.account_number, a.cached_balance
  FROM customers c 
  JOIN accounts a ON a.customer_id = c.id
 WHERE a.cached_balance = (
       SELECT MAX(a2.cached_balance) 
         FROM accounts a2 
        WHERE a2.customer_id = c.id
 )
 ORDER BY c.full_name;
```
* **Execution Output:**
  ```text
    full_name   |  account_number  | cached_balance 
  --------------+------------------+----------------
   Ananya Iyer  | INR-SAV-81A4C0E2 |      233000.00
   Arjun Nair   | INR-SAV-7A5F0C93 |       12000.00
   Rahul Sharma | INR-SAV-3BD2762D |      125000.00
   Sneha Kapoor | INR-SAV-2E6B8D14 |       64500.00
   Vikram Mehta | INR-CUR-9F0D3A71 |      310000.00
  (5 rows)
  ```

---

### 1.3 `NOT EXISTS` Subquery (Zero-Activity Discovery)
Isolate registered customers who have never initiated a transfer request:

```sql
SELECT c.full_name 
  FROM customers c
 WHERE NOT EXISTS (
       SELECT 1 
         FROM transfer_requests t 
        WHERE t.source_user_id = c.user_id
 )
 ORDER BY c.full_name;
```
* **Execution Output:**
  ```text
    full_name   
  --------------
   Arjun Nair
   Sneha Kapoor
  (2 rows)
  ```

---

### 1.4 `IN` Subquery with Set Evaluation
Find all accounts that have received funds sent by Rahul Sharma:

```sql
SELECT account_number 
  FROM accounts
 WHERE id IN (
       SELECT destination_account_id 
         FROM transfer_requests 
        WHERE source_user_id = (SELECT id FROM users WHERE username = 'rahul_sharma')
 )
 ORDER BY account_number;
```
* **Execution Output:**
  ```text
    account_number  
  ------------------
   INR-SAV-81A4C0E2
  (1 row)
  ```

---

## 2. Advanced Joins

Relational financial models distribute identity, account balances, and postings across separate tables. Joins synthesize these relationships without data duplication.

### 2.1 Multi-Table INNER JOIN (4-Table Complete Audit)
Joins `transfer_requests`, `users`, source `accounts`, destination `accounts`, and recipient `customers` to trace complete fund flow:

```sql
SELECT us.username AS sender, 
       sa.account_number AS from_account, 
       da.account_number AS to_account,
       dc.full_name AS recipient, 
       t.amount, 
       t.status
  FROM transfer_requests t
  JOIN users     us ON us.id = t.source_user_id
  JOIN accounts  sa ON sa.id = t.source_account_id
  JOIN accounts  da ON da.id = t.destination_account_id
  JOIN customers dc ON dc.id = da.customer_id
 ORDER BY t.created_at;
```

---

### 2.2 LEFT OUTER JOIN (Preserving System Internal Accounts)
Retrieves all bank accounts with owner details. Internal clearing accounts (`customer_id IS NULL`) are preserved rather than dropped:

```sql
SELECT a.account_number, 
       a.account_type, 
       COALESCE(c.full_name, '(bank internal)') AS owner
  FROM accounts a 
  LEFT JOIN customers c ON c.id = a.customer_id
 ORDER BY a.account_number;
```
* **Execution Output:**
  ```text
    account_number  |   account_type    |      owner      
  ------------------+-------------------+-----------------
   INR-CUR-5009D7C0 | CURRENT           | Rahul Sharma
   INR-CUR-9F0D3A71 | CURRENT           | Vikram Mehta
   INR-SAV-2E6B8D14 | SAVINGS           | Sneha Kapoor
   INR-SAV-3BD2762D | SAVINGS           | Rahul Sharma
   INR-SAV-7A5F0C93 | SAVINGS           | Arjun Nair
   INR-SAV-81A4C0E2 | SAVINGS           | Ananya Iyer
   INR-SAV-C47E19B5 | SAVINGS           | Vikram Mehta
   INR-SYS-CLEARING | INTERNAL_CLEARING | (bank internal)
  (8 rows)
  ```

---

### 2.3 SELF JOIN (Pairing Double-Entry Legs)
In a double-entry ledger, every transaction creates at least two rows in `ledger_entries`. A self-join reconstructs who paid whom by pairing the `DEBIT` and `CREDIT` rows of the same `transaction_id`:

```sql
SELECT t.transaction_type, 
       d_acc.account_number AS debited_account, 
       c_acc.account_number AS credited_account, 
       d.amount
  FROM ledger_entries d
  JOIN ledger_entries c ON c.transaction_id = d.transaction_id 
                       AND c.entry_type = 'CREDIT'
  JOIN ledger_transactions t ON t.id = d.transaction_id
  JOIN accounts d_acc ON d_acc.id = d.account_id
  JOIN accounts c_acc ON c_acc.id = c.account_id
 WHERE d.entry_type = 'DEBIT'
 ORDER BY t.created_at, c.sequence_num;
```

---

### 2.4 RIGHT OUTER JOIN + GROUP BY (Catalog Coverage)
Ensures every financial product listed in the catalog is reported, even if zero customers have invested in it:

```sql
SELECT p.code, COUNT(i.id) AS active_investments
  FROM investments i 
 RIGHT JOIN financial_products p ON p.id = i.product_id
 GROUP BY p.code 
 ORDER BY p.code;
```

---

## 3. Database Views

Views encapsulate complex multi-table analytics and real-time running totals behind simple virtual tables.

### 3.1 Customer Summary View (`v_customer_summary`)
Aggregates customer KYC status, count of accounts, total net worth, and historical transfers sent:

```sql
CREATE OR REPLACE VIEW v_customer_summary AS
SELECT c.full_name, 
       u.username, 
       c.kyc_status,
       COUNT(a.id) AS accounts,
       COALESCE(SUM(a.cached_balance), 0) AS net_worth,
       (SELECT COUNT(*) 
          FROM transfer_requests t 
         WHERE t.source_user_id = u.id 
           AND t.status = 'POSTED') AS transfers_sent
  FROM customers c
  JOIN users u ON u.id = c.user_id
  LEFT JOIN accounts a ON a.customer_id = c.id
 GROUP BY c.id, c.full_name, u.id, u.username, c.kyc_status;
```
* **Querying the View:**
  ```sql
  SELECT * FROM v_customer_summary ORDER BY net_worth DESC;
  ```
  ```text
    full_name   |   username   | kyc_status | accounts | net_worth | transfers_sent 
  --------------+--------------+------------+----------+-----------+----------------
   Vikram Mehta | vikram_mehta | VERIFIED   |        2 | 402000.00 |              1
   Ananya Iyer  | ananya_iyer  | VERIFIED   |        1 | 233000.00 |              1
   Rahul Sharma | rahul_sharma | VERIFIED   |        2 | 170000.00 |              1
   Sneha Kapoor | sneha_kapoor | VERIFIED   |        1 |  64500.00 |              0
   Arjun Nair   | arjun_nair   | REJECTED   |        1 |  12000.00 |              0
  (5 rows)
  ```

---

### 3.2 Account Statement View with SQL Window Functions (`v_account_statement`)
Computes customer passbook statements dynamically. The running balance is calculated via window function rather than stored statically:

```sql
CREATE OR REPLACE VIEW v_account_statement AS
SELECT e.account_id,
       t.id AS transaction_id,
       t.created_at,
       e.sequence_num,
       t.transaction_type,
       t.description,
       e.entry_type,
       e.amount,
       -- Window Function calculating cumulative balance:
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

### 3.3 Reconciliation & System Audit View (`v_account_reconciliation`)
Audits ledger integrity by comparing `cached_balance` against raw ledger sums. Proves zero mathematical drift:

```sql
CREATE OR REPLACE VIEW v_account_reconciliation AS
SELECT a.id AS account_id,
       a.account_number,
       a.account_type,
       a.status,
       a.cached_balance,
       COALESCE(SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END), 0) AS ledger_balance,
       a.cached_balance - COALESCE(SUM(CASE WHEN e.entry_type = 'CREDIT' THEN e.amount ELSE -e.amount END), 0) AS discrepancy,
       COUNT(e.id) AS leg_count
  FROM accounts a
  LEFT JOIN ledger_entries e ON e.account_id = a.id
 GROUP BY a.id, a.account_number, a.account_type, a.status, a.cached_balance;
```

---

## 4. Stored Procedures

PL/pgSQL stored procedures guarantee transactional consistency (ACID), implement concurrency controls, and eliminate deadlocks.

### 4.1 Fund Transfer Stored Procedure (`sp_transfer_funds`)
* **Signature:**
  ```sql
  CREATE OR REPLACE FUNCTION sp_transfer_funds(
      p_source_user_id UUID,
      p_idempotency_key VARCHAR,
      p_request_hash VARCHAR,
      p_source_account_id UUID,
      p_destination_account_id UUID,
      p_amount NUMERIC(15,2),
      p_description TEXT
  ) RETURNS UUID LANGUAGE plpgsql;
  ```

#### Architectural Highlights:
1. **Deadlock Avoidance via Sorted Lock Hierarchy:**
   ```sql
   -- Both accounts locked in ascending UUID order regardless of transfer direction:
   IF p_source_account_id < p_destination_account_id THEN
       SELECT * INTO v_src FROM accounts WHERE id = p_source_account_id FOR UPDATE;
       SELECT * INTO v_dst FROM accounts WHERE id = p_destination_account_id FOR UPDATE;
   ELSE
       SELECT * INTO v_dst FROM accounts WHERE id = p_destination_account_id FOR UPDATE;
       SELECT * INTO v_src FROM accounts WHERE id = p_source_account_id FOR UPDATE;
   END IF;
   ```
2. **Business Rule Verification:**
   - Ownership verification (`v_src.customer_id = (SELECT id FROM customers WHERE user_id = p_source_user_id)`).
   - Account status check (`v_src.status = 'ACTIVE'`).
   - Overdraft protection (`v_src.cached_balance >= p_amount`).
3. **Double-Entry Ledger Insertion:**
   - Inserts header in `ledger_transactions`.
   - Inserts DEBIT leg on source and CREDIT leg on destination in `ledger_entries`.
   - Updates `cached_balance` on both accounts atomically.

---

### 4.2 Compensating Reversal Procedure (`sp_reverse_transfer`)
* **Signature:**
  ```sql
  CREATE OR REPLACE FUNCTION sp_reverse_transfer(
      p_transfer_id UUID,
      p_admin_user_id UUID,
      p_reason TEXT
  ) RETURNS UUID LANGUAGE plpgsql;
  ```
* **Immutability Principle:** Financial records are **never deleted or modified**. `sp_reverse_transfer` checks that the caller has role `ADMIN`, verifies the transfer is currently `POSTED`, and posts an opposite transaction (crediting original sender, debiting original recipient).

---

## 5. User-Defined Functions (PL/pgSQL & SQL UDFs)

### 5.1 Account Number Masking Function (`fn_mask_account`)
An immutable SQL function that masks sensitive account numbers for public display, adhering to PCI-DSS standards:

```sql
CREATE OR REPLACE FUNCTION fn_mask_account(p_number VARCHAR) 
RETURNS VARCHAR LANGUAGE sql IMMUTABLE AS $$
    SELECT LPAD(RIGHT(p_number, 4), LENGTH(p_number), 'X')
$$;
```
* **Execution:**
  ```sql
  SELECT account_number, fn_mask_account(account_number) AS masked 
    FROM accounts WHERE customer_id IS NOT NULL;
  ```
  ```text
    account_number  |      masked      
  ------------------+------------------
   INR-CUR-5009D7C0 | XXXXXXXXXXXXD7C0
   INR-CUR-9F0D3A71 | XXXXXXXXXXXX3A71
   INR-SAV-2E6B8D14 | XXXXXXXXXXXX8D14
  ```

---

### 5.2 Customer Net Worth Valuation Function (`fn_customer_net_worth`)
A stable PL/pgSQL function computing aggregate liquid holdings for any given username:

```sql
CREATE OR REPLACE FUNCTION fn_customer_net_worth(p_username VARCHAR) 
RETURNS NUMERIC(15,2) LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_total NUMERIC(15,2);
BEGIN
    SELECT COALESCE(SUM(a.cached_balance), 0) INTO v_total
      FROM accounts a 
      JOIN customers c ON c.id = a.customer_id 
      JOIN users u ON u.id = c.user_id
     WHERE u.username = p_username;
    RETURN v_total;
END;
$$;
```

---

## 6. Explicit PL/pgSQL Cursors

Cursors enable sequential, tuple-by-tuple batch processing for operations that require multi-stage arithmetic across result sets.

### 6.1 Product Maturity Compound Yield Calculator
This PL/pgSQL block demonstrates declaration, opening, iterative record fetching, quarterly compounding calculation, and clean closure of an explicit cursor:

```sql
DO $$
DECLARE
    -- 1. Declare explicit cursor:
    cur_products CURSOR FOR
        SELECT code, min_amount, annual_yield_rate, term_months 
          FROM financial_products 
         WHERE is_active 
         ORDER BY code;
    rec        RECORD;
    v_maturity NUMERIC(15,2);
    v_count    INTEGER := 0;
BEGIN
    -- 2. Open cursor:
    OPEN cur_products;
    LOOP
        -- 3. Fetch row:
        FETCH cur_products INTO rec;
        EXIT WHEN NOT FOUND;
        
        -- Quarterly compound interest formula: A = P * (1 + r/400)^(n/3)
        v_maturity := ROUND(rec.min_amount * POWER(1 + rec.annual_yield_rate / 400.0, rec.term_months / 3.0), 2);
        
        RAISE NOTICE '% : % invested for % months at % %% -> Maturity: %',
            rec.code, rec.min_amount, rec.term_months, rec.annual_yield_rate, v_maturity;
        v_count := v_count + 1;
    END LOOP;
    -- 4. Close cursor:
    CLOSE cur_products;
    RAISE NOTICE '% financial products successfully processed', v_count;
END;
$$;
```
* **Execution Notices:**
  ```text
  NOTICE:  FD-12M-STD : 10000.00 invested for 12 months at 7.10 % -> Maturity: 10729.13
  NOTICE:  FD-36M-HY  : 25000.00 invested for 36 months at 7.75 % -> Maturity: 31473.70
  NOTICE:  MF-LIQ-GROWTH : 1000.00 invested for 3 months at 6.50 % -> Maturity: 1016.25
  NOTICE:  RD-24M-SYS : 5000.00 invested for 24 months at 6.80 % -> Maturity: 5721.87
  NOTICE:  TB-182D-SOV : 10000.00 invested for 6 months at 6.90 % -> Maturity: 10347.98
  NOTICE:  5 financial products successfully processed
  ```

---

## 7. Database Triggers

Triggers enforce non-bypassable business invariants directly within the PostgreSQL storage engine.

### 7.1 Row-Level Immutability Trigger (`trg_immutable_audit_logs`)
Prevents modification or deletion of financial audit entries:

```sql
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
```
* **Verification Test:**
  ```sql
  UPDATE audit_logs SET action = 'HACKED';
  -- Result: ERROR: Table audit_logs is strictly append-only; updates and deletes are prohibited
  ```

---

### 7.2 Deferred Double-Entry Balance Verification Trigger (`trg_verify_ledger_balance`)
Enforces the fundamental equation of accounting ($\sum \text{Debits} - \sum \text{Credits} = 0$). Declared `DEFERRABLE INITIALLY DEFERRED` to evaluate at `COMMIT`:

```sql
CREATE OR REPLACE FUNCTION verify_transaction_balance() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    v_delta NUMERIC(17,2);
BEGIN
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

CREATE CONSTRAINT TRIGGER trg_verify_ledger_balance
    AFTER INSERT ON ledger_entries
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION verify_transaction_balance();
```

---

### 7.3 Automatic Timestamp Maintenance Trigger (`trg_customers_touch`)
```sql
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_customers_touch 
    BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
```

---

## 8. Final Empirical Proof: The Mathematical Identity

Running the master reconciliation query proves that across all operations (transfers, reversals, and cursors), the books balance with **zero error**:

```sql
SELECT COUNT(*) FILTER (WHERE discrepancy <> 0) AS accounts_out_of_balance,
       SUM(cached_balance)                       AS system_total
  FROM v_account_reconciliation;
```

```text
 accounts_out_of_balance | system_total 
-------------------------+--------------
                       0 |         0.00
(1 row)
```

---

## 9. How to Reproduce This Review in 1 Command

The entire demonstration can be executed end-to-end using the pre-configured script:

```powershell
$env:PGPASSWORD = "Swaraj@10"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -h localhost -d finledger_review -f "c:\dbms project\finledger-ai\sql\review2.sql"
```
