"""Tests for connection health endpoint behavior."""

import asyncio
import os

os.environ.setdefault("JWT_SECRET", "unit-test-secret")

from routers import connection
from schemas import BackendStartupStatus, ConnectionStatus, StartupStatus, SubscriptionStartupStatus


class _FakeBloombergStatus:
    def __init__(self, status: str):
        self.status = status

    def model_dump(self):
        return {"status": self.status}


class _FakeBloomberg:
    def __init__(self, status: str, startup_status: StartupStatus | None = None):
        self._status = _FakeBloombergStatus(status)
        self._startup_status = startup_status or StartupStatus(
            phase="ready" if status == "connected" else "bloomberg_connecting",
            ready=status == "connected",
            message="ready" if status == "connected" else "connecting",
            backend=BackendStartupStatus(httpReady=True, startedAt="2026-04-23T13:00:00", uptime=10),
            bloomberg=ConnectionStatus(status=status),
            subscriptions=SubscriptionStartupStatus(
                ordersInitPaintDone=status == "connected",
                routesInitPaintDone=status == "connected",
                subscriptionFailed=False,
                marketDataConnected=False,
                orderCount=5 if status == "connected" else 0,
                routeCount=2 if status == "connected" else 0,
                ready=status == "connected",
            ),
        )

    def get_status(self):
        return self._status

    def get_startup_status(self):
        return self._startup_status


def test_health_check_treats_disabled_database_as_optional(monkeypatch):
    monkeypatch.setattr(connection.settings, "ENABLE_DB_PERSISTENCE", False)
    monkeypatch.setattr(connection, "get_bloomberg", lambda: _FakeBloomberg("connected"))

    response = asyncio.run(connection.health_check())

    assert response.success is True
    assert response.data["database"]["status"] == "disabled"
    assert response.data["database"]["message"] == "DB persistence disabled"


def test_health_check_reports_database_failure_when_enabled(monkeypatch):
    async def _fake_check_database_connection():
        return False, "dns failure"

    monkeypatch.setattr(connection.settings, "ENABLE_DB_PERSISTENCE", True)
    monkeypatch.setattr(connection, "get_bloomberg", lambda: _FakeBloomberg("connected"))
    monkeypatch.setattr(connection, "check_database_connection", _fake_check_database_connection)

    response = asyncio.run(connection.health_check())

    assert response.success is False
    assert response.data["database"]["status"] == "disconnected"
    assert response.data["database"]["message"] == "dns failure"


def test_startup_status_reports_subscription_warmup(monkeypatch):
    startup_status = StartupStatus(
        phase="subscriptions_warming",
        ready=False,
        message="Bloomberg connected; waiting for INIT_PAINT",
        backend=BackendStartupStatus(httpReady=True, startedAt="2026-04-23T13:00:00", uptime=42),
        bloomberg=ConnectionStatus(status="connected", uptime=12),
        subscriptions=SubscriptionStartupStatus(
            ordersInitPaintDone=True,
            routesInitPaintDone=False,
            subscriptionFailed=False,
            marketDataConnected=True,
            orderCount=18,
            routeCount=0,
            ready=False,
        ),
    )
    monkeypatch.setattr(connection, "get_bloomberg", lambda: _FakeBloomberg("connected", startup_status=startup_status))

    response = asyncio.run(connection.get_startup_status(user={}))

    assert response.success is True
    assert response.data["phase"] == "subscriptions_warming"
    assert response.data["backend"]["httpReady"] is True
    assert response.data["subscriptions"]["ordersInitPaintDone"] is True
    assert response.data["subscriptions"]["routesInitPaintDone"] is False


def test_startup_status_reports_error_when_subscription_failed(monkeypatch):
    startup_status = StartupStatus(
        phase="error",
        ready=False,
        message="Subscription failed",
        backend=BackendStartupStatus(httpReady=True, startedAt="2026-04-23T13:00:00", uptime=99),
        bloomberg=ConnectionStatus(status="connected", uptime=20),
        subscriptions=SubscriptionStartupStatus(
            ordersInitPaintDone=False,
            routesInitPaintDone=False,
            subscriptionFailed=True,
            marketDataConnected=False,
            orderCount=0,
            routeCount=0,
            ready=False,
        ),
    )
    monkeypatch.setattr(connection, "get_bloomberg", lambda: _FakeBloomberg("connected", startup_status=startup_status))

    response = asyncio.run(connection.get_startup_status(user={}))

    assert response.success is True
    assert response.data["phase"] == "error"
    assert response.data["subscriptions"]["subscriptionFailed"] is True
    assert response.message == "Subscription failed"