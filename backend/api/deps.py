"""Shared FastAPI dependencies for routers.

Provides ``verify_token``, ``audit_log``, and FastAPI ``Depends()``-based
service injection for routers.

Services are stored in ``app.state`` and injected via::

    from deps import get_bloomberg_service, get_broker_storage_service
    async def my_route(bloomberg = Depends(get_bloomberg_service)): ...
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
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


def init_services(bloomberg_service, broker_storage, repo_provider) -> None:
    """Wire the audit RepositoryProvider singleton.

    Called once from main.py after construction. Bloomberg/Broker storage
    services are now injected via app.state + Depends(); this function only
    handles the audit persistence provider for backward compatibility.
    """
    global _repo_provider
    _repo_provider = repo_provider


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
# FastAPI Depends() based service injection (canonical accessors).
# ---------------------------------------------------------------------------


def get_bloomberg_service(request: Request):
    """FastAPI Depends() accessor — resolves BloombergEMSXService from app.state."""
    return request.app.state.bloomberg_service


def get_broker_storage_service(request: Request):
    """FastAPI Depends() accessor — resolves BrokerAlgorithmStorageService from app.state."""
    return request.app.state.broker_storage
