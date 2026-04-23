"""Tests for connection health endpoint behavior."""

import asyncio
import os

os.environ.setdefault("JWT_SECRET", "unit-test-secret")

from routers import connection


class _FakeBloombergStatus:
    def __init__(self, status: str):
        self.status = status

    def model_dump(self):
        return {"status": self.status}


class _FakeBloomberg:
    def __init__(self, status: str):
        self._status = _FakeBloombergStatus(status)

    def get_status(self):
        return self._status


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