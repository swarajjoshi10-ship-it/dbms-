"""Load the review dataset (7 users, 5 customers, 8 accounts, 5 products, opening deposits).

    python -m scripts.seed                 # dataset only
    python -m scripts.seed --with-activity # plus demo transfers, alerts, a dispute and a money cycle

Every demo user signs in with the password in DEMO_PASSWORD.
"""
import argparse
import uuid
from decimal import Decimal

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Account, Customer, FinancialProduct, TransferRequest, User
from app.schemas import TransferIn
from app.audit import RequestMeta
from app.security import hash_password
from app.services import graph
from app.services.transfers import create_transfer

DEMO_PASSWORD = "FinLedger@2026"

USERS = [
    ("admin_system", "admin@finledger.in", "ADMIN"),
    ("priya_investigator", "priya@finledger.in", "STAFF"),
    ("rahul_sharma", "rahul@example.in", "CUSTOMER"),
    ("ananya_iyer", "ananya@example.in", "CUSTOMER"),
    ("vikram_mehta", "vikram@example.in", "CUSTOMER"),
    ("sneha_kapoor", "sneha@example.in", "CUSTOMER"),
    ("arjun_nair", "arjun@example.in", "CUSTOMER"),
]

CUSTOMERS = [
    ("rahul_sharma", "Rahul Sharma", "+91-9876543210", "ABCDE1234F", "2026-01-12 10:15+05:30"),
    ("ananya_iyer", "Ananya Iyer", "+91-9845012345", "BKXPI4521K", "2026-02-03 11:40+05:30"),
    ("vikram_mehta", "Vikram Mehta", "+91-9820098200", "CMNPM7788Q", "2026-03-21 16:05+05:30"),
    ("sneha_kapoor", "Sneha Kapoor", None, "DKZPK1029L", "2026-06-09 09:30+05:30"),
    ("arjun_nair", "Arjun Nair", "+91-9447001122", None, "2026-09-28 14:55+05:30"),
]

ACCOUNTS = [
    ("Rahul Sharma", "INR-SAV-3BD2762D", "SAVINGS", "150000.00"),
    ("Rahul Sharma", "INR-CUR-5009D7C0", "CURRENT", "40000.00"),
    ("Ananya Iyer", "INR-SAV-81A4C0E2", "SAVINGS", "220000.00"),
    ("Vikram Mehta", "INR-SAV-C47E19B5", "SAVINGS", "85000.00"),
    ("Vikram Mehta", "INR-CUR-9F0D3A71", "CURRENT", "310000.00"),
    ("Sneha Kapoor", "INR-SAV-2E6B8D14", "SAVINGS", "64500.00"),
    ("Arjun Nair", "INR-SAV-7A5F0C93", "SAVINGS", "12000.00"),
]

PRODUCTS = [
    ("12-Month Standard Fixed Deposit", "FD-12M-STD", "FIXED_DEPOSIT", "7.10", "10000.00", 12),
    ("36-Month High-Yield Fixed Deposit", "FD-36M-HY", "FIXED_DEPOSIT", "7.75", "25000.00", 36),
    ("24-Month Systematic Recurring Deposit", "RD-24M-SYS", "RECURRING_DEPOSIT", "6.80", "5000.00", 24),
    ("Simulated Liquid Debt Growth Fund", "MF-LIQ-GROWTH", "MUTUAL_FUND", "6.50", "1000.00", 3),
    ("182-Day Sovereign Treasury Bill", "TB-182D-SOV", "TREASURY_BILL", "6.90", "10000.00", 6),
]


def seed_dataset(db) -> bool:
    if db.scalar(select(User).where(User.username == "admin_system")):
        print("Dataset already present; skipping.")
        return False

    password_hash = hash_password(DEMO_PASSWORD)
    users = {}
    for username, email, role in USERS:
        users[username] = User(username=username, email=email, password_hash=password_hash, role=role)
        db.add(users[username])
    db.flush()

    customers = {}
    for username, name, phone, pan, joined in CUSTOMERS:
        customers[name] = Customer(user_id=users[username].id, full_name=name, phone=phone, pan_number=pan, created_at=joined)
        db.add(customers[name])
    db.flush()

    db.add(Account(customer_id=None, account_number="INR-SYS-CLEARING", account_type="INTERNAL_CLEARING"))
    accounts = {}
    for name, number, acc_type, _ in ACCOUNTS:
        accounts[number] = Account(customer_id=customers[name].id, account_number=number, account_type=acc_type,
                                   created_at=customers[name].created_at)
        db.add(accounts[number])
    for name, code, ptype, rate, minimum, term in PRODUCTS:
        db.add(FinancialProduct(name=name, code=code, product_type=ptype, annual_yield_rate=Decimal(rate),
                                min_amount=Decimal(minimum), term_months=term))
    db.flush()

    # Opening deposits are balanced postings against the clearing account.
    for _, number, _, amount in ACCOUNTS:
        db.execute(text("SELECT sp_post_deposit(:a, :amt, :d)"),
                   {"a": accounts[number].id, "amt": Decimal(amount), "d": f"Opening deposit {number}"})

    # KYC outcomes and the freeze of the account whose owner failed KYC (report section 6.5).
    for name in ("Rahul Sharma", "Ananya Iyer", "Vikram Mehta", "Sneha Kapoor"):
        customers[name].kyc_status = "VERIFIED"
    customers["Arjun Nair"].kyc_status = "REJECTED"
    db.execute(text("UPDATE accounts SET status = 'FROZEN', version = version + 1 WHERE account_number = 'INR-SAV-7A5F0C93'"))
    db.commit()
    print(f"Seeded {len(USERS)} users, {len(CUSTOMERS)} customers, {len(ACCOUNTS) + 1} accounts, {len(PRODUCTS)} products.")
    return True


def seed_activity(db) -> None:
    """A handful of transfers so the staff screens have something to show."""
    if db.scalar(select(TransferRequest.id).limit(1)):
        print("Transfers already present; skipping activity.")
        return
    meta = RequestMeta("127.0.0.1", "seed-script")
    by_name = {u.username: u for u in db.scalars(select(User))}
    acc = {a.account_number: a for a in db.scalars(select(Account))}

    def send(username, src, dst, amount, note):
        payload = TransferIn(source_account_id=acc[src].id, destination_account_number=dst,
                             amount=Decimal(amount), description=note)
        try:
            create_transfer(db, by_name[username], str(uuid.uuid4()), payload, meta)
        except Exception as exc:  # refused transfers are part of the demo
            print(f"  refused: {username} {amount} {src} -> {dst}: {getattr(exc, 'message', exc)}")

    send("rahul_sharma", "INR-SAV-3BD2762D", "INR-SAV-81A4C0E2", "2500.00", "Dinner split")
    send("rahul_sharma", "INR-SAV-3BD2762D", "INR-CUR-5009D7C0", "10000.00", "Move to current")
    send("ananya_iyer", "INR-SAV-81A4C0E2", "INR-SAV-C47E19B5", "18000.00", "Rent share")
    send("vikram_mehta", "INR-CUR-9F0D3A71", "INR-SAV-2E6B8D14", "4200.00", "Invoice 1042")
    # Suspicious: a new payee, a large amount and most of the balance in one go.
    send("sneha_kapoor", "INR-SAV-2E6B8D14", "INR-CUR-9F0D3A71", "65000.00", "Urgent - KYC update fee")
    send("vikram_mehta", "INR-CUR-9F0D3A71", "INR-SAV-81A4C0E2", "250000.00", "Property advance")
    # A money cycle: Rahul -> Ananya -> Vikram -> Rahul.
    send("rahul_sharma", "INR-CUR-5009D7C0", "INR-SAV-81A4C0E2", "30000.00", "Loan")
    send("ananya_iyer", "INR-SAV-81A4C0E2", "INR-SAV-C47E19B5", "29500.00", "Forward")
    send("vikram_mehta", "INR-SAV-C47E19B5", "INR-CUR-5009D7C0", "29000.00", "Return")
    # Refused: frozen account, insufficient funds.
    send("arjun_nair", "INR-SAV-7A5F0C93", "INR-SAV-3BD2762D", "1000.00", "From frozen account")
    send("rahul_sharma", "INR-CUR-5009D7C0", "INR-SAV-81A4C0E2", "9999999.00", "Too much")

    findings = graph.scan(db)
    print(f"Posted demo transfers; graph scan found {len(findings)} pattern(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-activity", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        seed_dataset(db)
        if args.with_activity:
            seed_activity(db)
    print(f"Demo password for every user: {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
