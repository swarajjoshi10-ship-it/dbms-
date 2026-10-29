import secrets
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit
from app.errors import DomainError, domain_error_from_db
from app.models import Account, Customer, User
from app.schemas import AccountOut, PayeePreview, StatementLine, StatementOut

TYPE_PREFIX = {"SAVINGS": "SAV", "CURRENT": "CUR", "INVESTMENT": "INV"}


def new_account_number(account_type: str) -> str:
    return f"INR-{TYPE_PREFIX[account_type]}-{secrets.token_hex(4).upper()}"


def open_account(db: Session, customer: Customer, account_type: str) -> Account:
    """Open an account with a fresh, unique number (retrying on the rare collision)."""
    for _ in range(5):
        account = Account(customer_id=customer.id, account_number=new_account_number(account_type), account_type=account_type)
        try:
            with db.begin_nested():
                db.add(account)
            return account
        except IntegrityError:
            continue
    raise DomainError(500, "ACCOUNT_NUMBER_EXHAUSTED", "Could not allocate an account number")


def mask_account_number(number: str) -> str:
    """Same as SQL: LPAD(RIGHT(account_number, 4), LENGTH(account_number), 'X')."""
    return number[-4:].rjust(len(number), "X")


def display_name(full_name: str | None) -> str:
    """'Rahul Sharma' -> 'R. Sharma' — enough to confirm a payee without exposing the full name."""
    if not full_name:
        return "FinLedger internal account"
    parts = full_name.split()
    return f"{parts[0][0]}. {parts[-1]}" if len(parts) > 1 else parts[0][0] + "."


def find_by_number(db: Session, account_number: str) -> Account:
    account = db.scalar(select(Account).where(Account.account_number == account_number.strip().upper()))
    if account is None:
        raise DomainError(404, "ACCOUNT_NOT_FOUND", "No account with that number")
    return account


def payee_preview(db: Session, account: Account) -> PayeePreview:
    owner = db.get(Customer, account.customer_id) if account.customer_id else None
    return PayeePreview(
        account_id=account.id,
        account_number_masked=mask_account_number(account.account_number),
        holder_display_name=display_name(owner.full_name if owner else None),
        account_type=account.account_type,
        status=account.status,
    )


def own_account(db: Session, customer: Customer, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.customer_id != customer.id:
        raise DomainError(404, "ACCOUNT_NOT_FOUND", "Account not found")
    return account


def post_deposit(db: Session, user: User, account: Account, amount, meta: RequestMeta) -> uuid.UUID:
    """A balanced INITIAL_DEPOSIT against INR-SYS-CLEARING via sp_post_deposit (FR4)."""
    try:
        txn_id = db.execute(
            text("SELECT sp_post_deposit(:acc, :amt, :desc)"),
            {"acc": account.id, "amt": amount, "desc": f"Deposit to {account.account_number}"},
        ).scalar_one()
        write_audit(db, user.id, "DEPOSIT_POSTED", "ACCOUNT", account.id, {"amount": str(amount), "transaction_id": str(txn_id)}, meta)
        db.commit()
    except Exception as exc:
        db.rollback()
        mapped = domain_error_from_db(exc)
        if mapped:
            raise mapped from None
        raise
    db.refresh(account)
    return txn_id


def statement(db: Session, account: Account, limit: int, offset: int) -> StatementOut:
    total = db.scalar(text("SELECT COUNT(*) FROM ledger_entries WHERE account_id = :a"), {"a": account.id})
    rows = db.execute(
        text(
            """
            SELECT entry_id, transaction_id, transaction_type, description, transfer_request_id,
                   entry_type, amount, running_balance, counterparty, created_at
              FROM v_account_statement
             WHERE account_id = :a
             ORDER BY created_at DESC, sequence_num DESC, entry_id DESC
             LIMIT :limit OFFSET :offset
            """
        ),
        {"a": account.id, "limit": limit, "offset": offset},
    ).mappings()
    return StatementOut(
        account=AccountOut.model_validate(account),
        total=total or 0,
        lines=[StatementLine(**r) for r in rows],
    )


def customer_accounts(db: Session, customer: Customer) -> list[Account]:
    return list(
        db.scalars(
            select(Account).where(Account.customer_id == customer.id).order_by(Account.account_type.desc(), Account.created_at)
        )
    )


def count_accounts(db: Session, customer: Customer, account_type: str) -> int:
    return db.scalar(
        select(func.count()).select_from(Account).where(Account.customer_id == customer.id, Account.account_type == account_type)
    ) or 0
