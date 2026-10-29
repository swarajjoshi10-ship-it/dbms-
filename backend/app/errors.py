from typing import Any


class DomainError(Exception):
    """A business-rule failure that maps to a clean HTTP error (never a stack trace)."""

    def __init__(self, status_code: int, code: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}


# SQLSTATE codes raised by the stored procedures (see migration d9e4a1b7c6f3).
PG_DOMAIN_ERRORS: dict[str, tuple[int, str]] = {
    "FLAMT": (422, "INVALID_AMOUNT"),
    "FLSAM": (422, "SAME_ACCOUNT"),
    "FLNFD": (404, "NOT_FOUND"),
    "FLOWN": (403, "NOT_ACCOUNT_OWNER"),
    "FLSTS": (409, "ACCOUNT_NOT_ACTIVE"),
    "FLNSF": (422, "INSUFFICIENT_FUNDS"),
    "FLINT": (422, "ACCOUNT_TYPE_NOT_ALLOWED"),
    "FLPRD": (404, "PRODUCT_UNAVAILABLE"),
    "FLMIN": (422, "BELOW_MINIMUM"),
    "FLREV": (409, "NOT_REVERSIBLE"),
    "FLROL": (403, "FORBIDDEN"),
}


def pg_error_parts(exc: BaseException) -> tuple[str | None, str]:
    """Return (sqlstate, primary message) of a psycopg error wrapped by SQLAlchemy."""
    orig = getattr(exc, "orig", exc)
    sqlstate = getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or str(orig).splitlines()[0]
    return sqlstate, message


def domain_error_from_db(exc: BaseException) -> DomainError | None:
    sqlstate, message = pg_error_parts(exc)
    if sqlstate in PG_DOMAIN_ERRORS:
        status, code = PG_DOMAIN_ERRORS[sqlstate]
        return DomainError(status, code, message)
    return None
