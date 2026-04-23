"""
Shared FastAPI dependencies for routers.

Provides ``verify_token``, ``audit_log``, and service accessor functions
that any router can import without pulling in main.py.

Call ``init_services(bloomberg_service, broker_storage)`` from main.py
once all singletons are ready.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from auth import AuthManager
from config import settings
from service_provider import RepositoryProvider
from services.auth_service import authenticate as _authenticate

logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Verify JWT token for API authentication — delegates to auth_service."""
    token = credentials.credentials if credentials else None
    return _authenticate(token)


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

# Injected by init_services()
_repo_provider: Optional[RepositoryProvider] = None


def audit_log(action: str, user: str, details: dict) -> None:
    """Log trading action for audit — with optional DB persistence."""
    if settings.ENABLE_AUDIT_LOG:
        logger.info(f"AUDIT: {action} | User: {user} | Details: {json.dumps(details)}")
    if _repo_provider and _repo_provider.is_active:
        asyncio.ensure_future(
            _repo_provider.persist_audit_event(
                action=action,
                actor=user,
                endpoint=action,
                result="ok",
                payload_summary=json.dumps(details)[:500] if details else None,
            )
        )


# ---------------------------------------------------------------------------
# Service accessors — set from main.py before first request
# ---------------------------------------------------------------------------

_bloomberg_service = None
_broker_storage = None


def init_services(bloomberg_service, broker_storage, repo_provider) -> None:
    """Wire runtime singletons. Called once from main.py after construction."""
    global _bloomberg_service, _broker_storage, _repo_provider
    _bloomberg_service = bloomberg_service
    _broker_storage = broker_storage
    _repo_provider = repo_provider


def get_bloomberg():
    """Return the BloombergEMSXService singleton."""
    return _bloomberg_service


def get_broker_storage():
    """Return the BrokerAlgorithmStorageService singleton."""
    return _broker_storage
