"""
Application configuration — Settings class and validated singleton.

Extracted from main.py so that routers and services can import ``settings``
without pulling in the entire application module.
"""

from __future__ import annotations

import os
import logging
from typing import List

logger = logging.getLogger("main")


class Settings:
    """Application settings from environment variables."""

    # Bloomberg Configuration
    BLOOMBERG_HOST: str = os.getenv("BLOOMBERG_HOST", "localhost")
    BLOOMBERG_PORT: int = int(os.getenv("BLOOMBERG_PORT", "8194"))
    BLOOMBERG_TIMEOUT: int = int(os.getenv("BLOOMBERG_TIMEOUT", "60000"))

    # API Configuration
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "3000"))
    API_WORKERS: int = int(os.getenv("API_WORKERS", "1"))

    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://emsx:emsx@postgres:5432/emsx")
    DATABASE_MIGRATION_URL: str = os.getenv("DATABASE_MIGRATION_URL", "postgresql+psycopg://emsx:emsx@postgres:5432/emsx")

    # Security
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))

    # CORS
    ALLOWED_ORIGINS: List[str] = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:80").split(",")

    # Trading
    ALLOWED_TRADERS: List[str] = os.getenv("ALLOWED_TRADERS", "").split(",")
    MAX_BATCH_SIZE: int = int(os.getenv("MAX_BATCH_SIZE", "100"))

    # Batch route / modify-route operations (separate from MAX_BATCH_SIZE which
    # is used by /api/orders/batch-update for legacy reasons).
    BATCH_ROUTE_MAX_SIZE: int = int(os.getenv("BATCH_ROUTE_MAX_SIZE", "500"))

    # Concurrent in-flight EMSX submissions per batch.
    BATCH_CONCURRENCY: int = int(os.getenv("BATCH_CONCURRENCY", "5"))

    # Size of the dedicated request session pool (N=1 = legacy single-session).
    # Multiple sessions allow concurrent EMSX RouteEx submissions.
    REQUEST_SESSION_POOL_SIZE: int = int(os.getenv("REQUEST_SESSION_POOL_SIZE", "1"))

    # Pre-trade compliance thresholds (USD). Values failing these bounds are
    # hard-blocked. See services/compliance_service.py.
    USD_NOTIONAL_MIN: float = float(os.getenv("USD_NOTIONAL_MIN", "10000"))
    USD_NOTIONAL_MAX: float = float(os.getenv("USD_NOTIONAL_MAX", "49000000"))

    # Odd lot detection markets
    ODD_LOT_MARKETS: List[str] = [
        m.strip().upper()
        for m in os.getenv("ODD_LOT_MARKETS", "JP,US").split(",")
        if m.strip()
    ]

    # Features
    ENABLE_REALTIME: bool = os.getenv("ENABLE_REALTIME", "true").lower() == "true"
    ENABLE_AUDIT_LOG: bool = os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true"

    # Trader identity
    EMSXVIEW_TRADER_NAME: str = os.getenv("EMSXVIEW_TRADER_NAME", "")

    # Development mode
    BYPASS_AUTH: bool = os.getenv("BYPASS_AUTH", "false").lower() == "true"

    # Persistence
    ENABLE_DB_PERSISTENCE: bool = os.getenv("ENABLE_DB_PERSISTENCE", "false").lower() == "true"

    # Optional module routers — comma-separated "module:label" pairs.
    # Set to empty string to disable all optional modules.
    # Set to "*" or "all" to load all known optional modules.
    # Default loads DatabaseView.
    # Example: EMSXVIEW_OPTIONAL_MODULES=costview:CostView,database:DB
    OPTIONAL_MODULES: str = os.getenv(
        "EMSXVIEW_OPTIONAL_MODULES",
        "database:DatabaseView",
    )


def _validate_settings(s: Settings) -> None:
    """Validate critical settings on startup."""
    if not s.BYPASS_AUTH and not s.JWT_SECRET:
        raise ValueError(
            "JWT_SECRET environment variable must be set. "
            "Generate a secure key with: openssl rand -hex 32"
        )
    weak_secrets = ["your-secret-key", "change-in-production", "secret", "password"]
    if s.JWT_SECRET and any(weak in s.JWT_SECRET.lower() for weak in weak_secrets):
        logger.warning("JWT_SECRET appears to be using a weak/default value.")
    logger.info(f"Settings validated: BYPASS_AUTH={s.BYPASS_AUTH}, JWT_SECRET set={bool(s.JWT_SECRET)}")
    logger.info(f"Odd lot detection enabled for markets: {s.ODD_LOT_MARKETS}")
    logger.info(f"DB persistence: ENABLE_DB_PERSISTENCE={s.ENABLE_DB_PERSISTENCE}")


settings = Settings()
_validate_settings(settings)
