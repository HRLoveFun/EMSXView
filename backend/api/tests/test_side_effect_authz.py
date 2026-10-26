"""A05（M3）— 副作用端点角色校验 + debug 路由条件注册测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from deps import verify_token  # noqa: E402
from routers import broker, connection, debug, orders_handoff  # noqa: E402


def _client(router, *, state: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    for key, value in (state or {}).items():
        setattr(app.state, key, value)
    app.dependency_overrides[verify_token] = lambda: {"sub": "v1", "role": "viewer"}
    return TestClient(app)


def test_reconnect_requires_admin():
    client = _client(connection.router, state={"bloomberg_service": MagicMock()})
    assert client.post("/api/connection/reconnect").status_code == 403


def test_broker_refresh_requires_admin():
    client = _client(
        broker.router,
        state={"bloomberg_service": MagicMock(), "broker_storage": MagicMock()},
    )
    assert client.post("/api/broker-algorithms/refresh").status_code == 403


def test_post_trade_handoff_requires_trade():
    client = _client(orders_handoff.router)
    assert client.post("/api/executions/handoff/post-trade", json={}).status_code == 403


def test_debug_query_round_lot_requires_admin():
    client = _client(debug.router, state={"bloomberg_service": MagicMock()})
    assert client.post("/api/debug/query-round-lot", params={"ticker": "AAPL"}).status_code == 403


def test_debug_routes_hidden_without_debug():
    """DEBUG 未设（默认）→ /api/debug/* 404（不注册路由）。"""
    env = {
        **os.environ,
        "DEBUG": "false",
        "JWT_SECRET": "testsecret",
        "BYPASS_AUTH": "true",
    }
    code = (
        "import main;"
        "from fastapi.testclient import TestClient;"
        "print(TestClient(main.app).get('/api/debug/round-lot-sizes').status_code)"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", code], cwd=str(API_ROOT), env=env, timeout=90
    )
    assert output.decode("utf-8", errors="replace").strip().splitlines()[-1] == "404"
