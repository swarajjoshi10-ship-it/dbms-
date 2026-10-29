import os
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/finledger"
    )
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_minutes: int = int(os.getenv("JWT_MINUTES", "60"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    )
    # Demo deposits let customers add money without a real payment rail.
    max_demo_deposit: Decimal = Decimal("100000.00")
    # Fraud alerts at or above this score appear in the staff triage queue.
    alert_threshold: Decimal = Decimal("0.4000")


settings = Settings()
