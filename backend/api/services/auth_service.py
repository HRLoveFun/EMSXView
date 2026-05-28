"""
Authentication service — encapsulates auth modes and policy checks.

Supports three modes:
- **bypass**: development-only, returns a fixed trader identity
- **jwt**: production mode with JWT token validation
- **policy**: (future) desk/trader ownership and action authorization

This service is used by ``deps.verify_token`` and can be extended with
desk-level ACL rules without touching the router layer.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from auth import AuthManager
from config import settings

logger = logging.getLogger("main")

# Fixed identity for bypass mode
_BYPASS_IDENTITY = {
    "sub": "bloomberg_local",
    "name": "Bloomberg Terminal User",
    "role": "trader",
}


def authenticate(token: Optional[str]) -> dict:
    """Authenticate a request and return the user identity dict.

    Parameters
    ----------
    token : str or None
        Bearer token from the Authorization header.

    Returns
    -------
    dict
        User identity with at least ``sub``, ``name``, ``role`` keys.

    Raises
    ------
    HTTPException 401
        If authentication fails.
    """
    if settings.BYPASS_AUTH:
        logger.debug("Auth bypassed for development mode")
        return _BYPASS_IDENTITY

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return AuthManager.verify_token(token)


def check_trader_ownership(user: dict, trader_name: str) -> bool:
    """Check if the authenticated user owns the given trader identity.

    In bypass mode, ownership is always granted.  In JWT mode, the
    ``sub`` claim must match the trader name.
    """
    if settings.BYPASS_AUTH:
        return True
    return user.get("sub", "").lower() == trader_name.lower()


def is_admin(user: dict) -> bool:
    """Return True if the user has admin role."""
    return user.get("role", "") == "admin"
