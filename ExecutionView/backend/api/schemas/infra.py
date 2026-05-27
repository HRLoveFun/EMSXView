"""Infrastructure schemas — connection, startup, auth."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel


class ConnectionStatus(BaseModel):
    """Bloomberg connection status."""

    status: Literal["connected", "disconnected", "connecting", "error"]
    message: Optional[str] = None
    lastConnected: Optional[str] = None
    uptime: Optional[int] = None


class BackendStartupStatus(BaseModel):
    """Backend process readiness snapshot."""

    httpReady: bool
    startedAt: Optional[str] = None
    uptime: Optional[int] = None


class SubscriptionStartupStatus(BaseModel):
    """EMSX subscription warmup status."""

    ordersInitPaintDone: bool
    routesInitPaintDone: bool
    subscriptionFailed: bool
    marketDataConnected: bool
    orderCount: int
    routeCount: int
    ready: bool


class StartupStatus(BaseModel):
    """Composite startup state for frontend warmup UX."""

    phase: Literal["backend_starting", "bloomberg_connecting", "subscriptions_warming", "ready", "error"]
    ready: bool
    message: Optional[str] = None
    backend: BackendStartupStatus
    bloomberg: ConnectionStatus
    subscriptions: SubscriptionStartupStatus


class LoginRequest(BaseModel):
    """Login credentials."""

    username: str
    password: str
