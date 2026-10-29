from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit, write_audit_independent
from app.db import get_db
from app.deps import get_current_user, request_meta
from app.errors import DomainError
from app.models import Customer, User
from app.schemas import CustomerOut, LoginIn, MeOut, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services.accounts import open_account

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """FR1/FR2/FR3: a customer user, their KYC profile (PENDING) and a first savings account."""
    taken = db.scalar(select(User).where(or_(User.username == body.username, User.email == str(body.email).lower())))
    if taken:
        raise DomainError(409, "USER_EXISTS", "That username or email is already registered")
    try:
        user = User(username=body.username, email=str(body.email).lower(), password_hash=hash_password(body.password), role="CUSTOMER")
        db.add(user)
        db.flush()
        customer = Customer(user_id=user.id, full_name=body.full_name, phone=body.phone or None, pan_number=body.pan_number)
        db.add(customer)
        db.flush()
        account = open_account(db, customer, "SAVINGS")
        write_audit(db, user.id, "USER_REGISTERED", "USER", user.id, {"account_number": account.account_number}, meta)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "USER_EXISTS", "That username or email is already registered") from None
    token, expires = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if not verify_password(body.password, user.password_hash if user else None) or not user.is_active:
        write_audit_independent(user.id if user else None, "AUTH_LOGIN_FAILURE", "USER", body.username[:64], {}, meta)
        raise DomainError(401, "INVALID_CREDENTIALS", "Incorrect username or password")
    write_audit(db, user.id, "AUTH_LOGIN_SUCCESS", "USER", user.id, {}, meta)
    db.commit()
    token, expires = create_access_token(user.id, user.role)
    return TokenOut(access_token=token, expires_in=expires, user=UserOut.model_validate(user))


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = db.scalar(select(Customer).where(Customer.user_id == user.id))
    return MeOut(user=UserOut.model_validate(user), customer=CustomerOut.model_validate(customer) if customer else None)
