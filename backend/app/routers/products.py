import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit import RequestMeta, write_audit
from app.db import get_db
from app.deps import get_current_user, get_customer, request_meta, require_admin
from app.errors import DomainError, domain_error_from_db
from app.models import Customer, FinancialProduct, Investment, User
from app.schemas import InvestIn, InvestmentOut, ProductIn, ProductOut, ProductPatch

router = APIRouter(prefix="/api", tags=["products"])


@router.get("/products", response_model=list[ProductOut])
def list_products(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(FinancialProduct).order_by(FinancialProduct.product_type, FinancialProduct.code)
    if user.role == "CUSTOMER":
        query = query.where(FinancialProduct.is_active)
    return db.scalars(query).all()


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, admin: User = Depends(require_admin), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    product = FinancialProduct(**body.model_dump())
    db.add(product)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DomainError(409, "PRODUCT_EXISTS", "A product with that code already exists") from None
    write_audit(db, admin.id, "PRODUCT_CREATED", "PRODUCT", product.id, {"code": product.code}, meta)
    db.commit()
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: uuid.UUID, body: ProductPatch, admin: User = Depends(require_admin),
    db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta),
):
    product = db.get(FinancialProduct, product_id)
    if product is None:
        raise DomainError(404, "PRODUCT_NOT_FOUND", "Product not found")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(product, field, value)
    write_audit(db, admin.id, "PRODUCT_UPDATED", "PRODUCT", product.id, {k: str(v) for k, v in changes.items()}, meta)
    db.commit()
    return product


def _investment_out(inv: Investment) -> InvestmentOut:
    return InvestmentOut(
        id=inv.id, product_code=inv.product.code, product_name=inv.product.name, product_type=inv.product.product_type,
        principal=inv.principal, annual_yield_rate=inv.annual_yield_rate, start_date=inv.start_date,
        maturity_date=inv.maturity_date, expected_maturity_value=inv.expected_maturity_value, status=inv.status,
    )


@router.get("/investments", response_model=list[InvestmentOut])
def list_investments(customer: Customer = Depends(get_customer), db: Session = Depends(get_db)):
    rows = db.scalars(select(Investment).where(Investment.customer_id == customer.id).order_by(Investment.created_at.desc()))
    return [_investment_out(i) for i in rows]


@router.post("/investments", response_model=InvestmentOut, status_code=201)
def invest(body: InvestIn, customer: Customer = Depends(get_customer), db: Session = Depends(get_db), meta: RequestMeta = Depends(request_meta)):
    """Buy a simulated deposit product: an INVESTMENT_PURCHASE posting via sp_purchase_investment."""
    try:
        investment_id = db.execute(
            text("SELECT sp_purchase_investment(:user, :acc, :product, :amount)"),
            {"user": customer.user_id, "acc": body.funding_account_id, "product": body.product_id, "amount": body.amount},
        ).scalar_one()
        write_audit(db, customer.user_id, "INVESTMENT_PURCHASED", "INVESTMENT", investment_id, {"amount": str(body.amount)}, meta)
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        mapped = domain_error_from_db(exc)
        if mapped is None:
            raise
        raise mapped from None
    return _investment_out(db.get(Investment, investment_id))
