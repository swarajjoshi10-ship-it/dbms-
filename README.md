# FinLedger-AI

An auditable double-entry financial transaction system with AI-assisted (advisory) fraud detection.
BCSE302P Database Systems project, VIT Vellore. This is the implementation of the Review 1 report.

Every financial rule is enforced **inside PostgreSQL**, so it holds even if application code is bypassed:

| Rule | Where it is enforced |
|---|---|
| Debits = credits in every posting (BR8) | Deferred constraint trigger `trg_verify_ledger_balance` |
| Ledger, ledger headers and audit log are append-only (BR9) | `BEFORE UPDATE/DELETE` and `BEFORE TRUNCATE` triggers |
| No negative customer balance, INR only, valid roles/statuses (BR1–BR7) | `CHECK` constraints |
| No double spend, no deadlocks | `sp_transfer_funds` locks both accounts in ascending id order (`FOR NO KEY UPDATE`) |
| Idempotent retries (BR11) | `UNIQUE (source_user_id, idempotency_key)` + SHA-256 request hash |
| Failed transfers leave evidence (BR12) | FAILED row + audit row written in a separate transaction |
| Corrections are new postings (BR13) | `sp_reverse_transfer` (admin only) |
| `cached_balance` = Σ credits − Σ debits (BR15) | `v_account_reconciliation` + admin reconciliation page |
| Fraud scores are advisory (BR14) | Scored after commit; only staff change an alert's status |

## Layout

```
finledger-ai/
├── backend/                 FastAPI + SQLAlchemy 2 + Alembic (Python 3.12)
│   ├── alembic/versions/    the schema: tables, triggers, stored procedures, views
│   ├── app/                 API (routers/), business services (services/), ML model (ml/)
│   ├── scripts/seed.py      the Review 1 dataset (7 users, 5 customers, 8 accounts, 5 products)
│   └── tests/               pytest against a real PostgreSQL database (54 tests)
├── frontend/                React 19 + TypeScript + Vite + Tailwind CSS
└── sql/
    ├── review1.sql          every statement in sections 4–8 of the Review 1 report
    └── review2.sql          joins, subqueries, views, procedures, functions, cursor, triggers
```

## Prerequisites

- PostgreSQL 16 (14+ works), with `psql` on your PATH
- Python 3.12
- Node.js 20+

## 1. Database

```bash
psql -U postgres -c "CREATE DATABASE finledger"
```

## 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Point the app at your database (PowerShell shown; use `export` on macOS/Linux):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/finledger"
$env:JWT_SECRET   = "change-me-to-a-long-random-string"
```

Create the schema, train the fraud model and load the demo data:

```bash
alembic upgrade head
python -m app.ml.model
python -m scripts.seed --with-activity
uvicorn app.main:app --reload --port 8000
```

API docs (Swagger): http://localhost:8000/docs

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Every demo user's password is **`FinLedger@2026`** (set in `backend/scripts/seed.py`):

| User | Role | Try |
|---|---|---|
| `rahul_sharma` | Customer | Send money (PayeeGuard preview), statement with running balance, invest |
| `sneha_kapoor` | Customer | Her ₹65,000 "KYC fee" transfer was flagged; raise a dispute |
| `arjun_nair` | Customer | KYC rejected, account frozen: transfers are refused and recorded as FAILED |
| `priya_investigator` | Staff | Review fraud alerts, run the graph scan, investigate disputes, read the audit trail |
| `admin_system` | Admin | Everything staff can do, plus reconciliation, reversals, freezing accounts and products |

## Tests

Tests need their own empty database:

```bash
psql -U postgres -c "CREATE DATABASE finledger_test"
cd backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/finledger_test"
pytest
```

They cover the database rules directly (unbalanced posting refused at COMMIT, append-only tables, every
CHECK), the API (auth, ownership, idempotent retries, failed-transfer evidence), concurrency
(10 parallel withdrawals never overdraw; opposite transfers never deadlock), reversals,
reconciliation, fraud review, graph cycles, disputes and investments.

Frontend unit tests: `cd frontend && npm test`.

## Reproducing the report (Review 1) and the Review 2 SQL

`review1.sql` expects an **empty** schema (do not run the seed script on this database):

```bash
psql -U postgres -c "CREATE DATABASE finledger_review"
cd backend
alembic -x db=finledger_review upgrade head
psql -U postgres -d finledger_review -f ../sql/review1.sql
psql -U postgres -d finledger_review -f ../sql/review2.sql
```

Some statements fail on purpose: each one demonstrates a constraint or trigger and prints the same
error the report shows. The constraint inventory (section 5.1) returns the report's 28 rows. The
balances, aggregates and double-entry proof match the report's outputs.

## Fraud scoring

After a transfer commits, `app/services/fraud.py` computes eight behavioural features in SQL: amount,
ratio to the sender's average, hour (IST), first transfer to this payee, account age, transfers in the
last hour, share of the balance sent, and distinct senders to the payee in 24 hours. The final score
blends 60% Random Forest probability (`app/ml/model.py`, trained on a documented synthetic population)
with 40% rule score. Bands: below 0.40 low, below 0.70 medium, otherwise high. Each score stores its
rule flags, the feature snapshot and a plain-language explanation. The **Fraud Lab** page evaluates the
model on fresh synthetic data. The **graph scan** finds money cycles (recursive CTE), fan-in mule
accounts and rapid pass-through accounts.

## Notes

- Money is `NUMERIC(15,2)` in PostgreSQL and `Decimal` in Python; floating point is never used for balances.
- Passwords are hashed with Argon2id. JWTs last 60 minutes and are kept in `sessionStorage`.
- Customers never see fraud scores. Staff can't move money. Only admins can reverse transfers.
