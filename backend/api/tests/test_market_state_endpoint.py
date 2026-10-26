"""057 DL-15 — 盘中市场状态端点测试（开关两态 + WS 心跳）。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# platform_data 为 editable 安装（指向主树）；worktree 内必须优先本仓副本
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import os  # noqa: E402

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from config import settings  # noqa: E402
from deps import get_bloomberg_service  # noqa: E402
from routers import market_state  # noqa: E402
from services import market_state_service as mss  # noqa: E402


def _bloomberg() -> SimpleNamespace:
    return SimpleNamespace(
        _intraday_quotes={
            "AAPL US Equity": {"BID": 100.0, "ASK": 100.5, "LAST_PRICE": 100.2},
        }
    )


def _client(bloomberg=None) -> TestClient:
    app = FastAPI()
    app.include_router(market_state.router)
    app.state.bloomberg_service = bloomberg or _bloomberg()
    return TestClient(app)


def test_snapshot_disabled_by_default(monkeypatch):
    """开关关闭：返回 enabled:false（不报错、不触发快照构建）。"""
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", False)
    response = _client(bloomberg=None).get("/api/market-state/snapshot")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["enabled"] is False
    assert body["tickers"] == []


def test_snapshot_enabled_returns_tickers(monkeypatch):
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", True)
    monkeypatch.setattr(market_state, "_baseline_lookup", lambda tickers: {})
    response = _client().get("/api/market-state/snapshot")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["enabled"] is True
    assert len(body["tickers"]) == 1
    state = body["tickers"][0]
    assert state["equ_ticker"] == "AAPL US Equity"
    assert state["spread_bps"] == pytest.approx(49.88, abs=0.05)
    assert state["schema_version"] == "market-state-v1"


def test_ws_pushes_disabled_heartbeat(monkeypatch):
    """开关关闭：WS 推送 enabled:false 心跳（不触发构建）。"""
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", False)
    with _client(bloomberg=None).websocket_connect("/ws/market-state") as ws:
        message = ws.receive_json()
    assert message["type"] == "market_state"
    assert message["data"]["enabled"] is False


def test_ws_pushes_snapshot_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", True)
    monkeypatch.setattr(market_state, "_baseline_lookup", lambda tickers: {})
    with _client().websocket_connect("/ws/market-state") as ws:
        message = ws.receive_json()
    assert message["type"] == "market_state"
    assert message["data"]["enabled"] is True
    assert message["data"]["tickers"][0]["equ_ticker"] == "AAPL US Equity"
