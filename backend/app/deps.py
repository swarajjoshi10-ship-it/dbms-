import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.audit import RequestMeta
from app.db import get_db
from app.errors import DomainError
from app.models import Customer, User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise DomainError(401, "NOT_AUTHENTICATED", "Sign in to continue")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise DomainError(401, "INVALID_TOKEN", "Your session is invalid or has expired") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise DomainError(401, "INVALID_TOKEN", "Your session is invalid or has expired")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise DomainError(403, "FORBIDDEN", "You do not have permission for this action")
        return user

    return checker


require_customer = require_roles("CUSTOMER")
require_staff = require_roles("STAFF", "ADMIN")
require_admin = require_roles("ADMIN")


def get_customer(user: User = Depends(require_customer), db: Session = Depends(get_db)) -> Customer:
    customer = db.query(Customer).filter(Customer.user_id == user.id).one_or_none()
    if customer is None:
        raise DomainError(403, "NO_CUSTOMER_PROFILE", "This user has no customer profile")
    return customer


def request_meta(request: Request) -> RequestMeta:
    return RequestMeta(request.client.host if request.client else None, request.headers.get("user-agent"))
