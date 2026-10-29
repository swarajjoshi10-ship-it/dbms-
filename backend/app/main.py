import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.errors import DomainError, domain_error_from_db
from app.ml import model as ml
from app.routers import accounts, admin, auth, disputes, fraud, products, transfers

log = logging.getLogger("finledger")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the fraud model in the background so the first transfer is not slowed down by it.
    threading.Thread(target=ml.get_model, daemon=True).start()
    yield


app = FastAPI(
    title="FinLedger-AI", version="1.0.0", description="Auditable double-entry ledger with advisory fraud detection",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)

for module in (auth, accounts, transfers, products, fraud, disputes, admin):
    app.include_router(module.router)


@app.exception_handler(DomainError)
async def domain_error_handler(_: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "detail": exc.message, **exc.extra})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "VALIDATION_ERROR", "detail": "Some fields are invalid", "fields": errors})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    # A database rule fired that the service did not anticipate: still a clean, mapped error.
    mapped = domain_error_from_db(exc)
    if mapped:
        return JSONResponse(status_code=mapped.status_code, content={"error": mapped.code, "detail": mapped.message})
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "detail": "Something went wrong. Please try again."})


@app.get("/api/health")
def health():
    return {"status": "ok"}
