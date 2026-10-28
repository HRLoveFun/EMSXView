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
from platform_data.contracts import MARKET_STATE_SCHEMA_VERSION  # noqa: E402
from routers import market_state  # noqa: E402
from services import market_state_service as mss  # noqa: E402


def _bloomberg() -> SimpleNamespace:
    return SimpleNamespace(
        _intraday_quotes={
            "AAPL US Equity": {"BID": 100.0, "ASK": 100.5, "LAST_PRICE": 100.2},
            "MSFT US Equity": {"BID": 400.0, "ASK": 400.4, "LAST_PRICE": 400.2},
        }
    )


def _client(bloomberg=None) -> TestClient:
    app = FastAPI()
    app.include_router(market_state.router)
    app.state.bloomberg_service = bloomberg or _bloomberg()
    return TestClient(app)


def test_monitor_thresholds_endpoint():
    """MonitorBoard 服务端默认阈值（版本化，替代前端 localStorage 常数）。"""
    response = _client().get("/api/market-state/thresholds")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["version"] == "monitor-thresholds-v1"
    assert data["monitor"]["dollarValueLow"] == 10_000
    assert data["monitor"]["dollarValueHigh"] == 49_000_000


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
    assert len(body["tickers"]) == 2
    by_ticker = {state["equ_ticker"]: state for state in body["tickers"]}
    state = by_ticker["AAPL US Equity"]
    assert state["spread_bps"] == pytest.approx(49.88, abs=0.05)
    assert state["schema_version"] == MARKET_STATE_SCHEMA_VERSION


def test_snapshot_filters_by_ticker_whitelist(monkeypatch):
    """MarketView 股票池只取池内标的：白名单外的订阅标的不出现在载荷里。"""
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", True)
    monkeypatch.setattr(market_state, "_baseline_lookup", lambda tickers: {})
    response = _client().get("/api/market-state/snapshot?tickers=MSFT%20US%20Equity")
    assert response.status_code == 200
    tickers = [state["equ_ticker"] for state in response.json()["data"]["tickers"]]
    assert tickers == ["MSFT US Equity"]


def test_snapshot_rejects_oversized_ticker_list(monkeypatch):
    monkeypatch.setattr(settings, "EMSXVIEW_INTRADAY_STATE_ENABLED", True)
    oversized = ",".join(f"T{i} US Equity" for i in range(market_state.MAX_TICKERS + 1))
    response = _client().get(f"/api/market-state/snapshot?tickers={oversized}")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_gateway_broadcasts_market_state():
    """网关广播 market_state 事件（真实 WS 握手属部署期观测，不在 CI）。"""
    import json

    from services.realtime_gateway import realtime_gw

    sent: list[str] = []

    class _FakeWS:
        async def send_text(self, text: str) -> None:
            sent.append(text)

    fake = _FakeWS()
    realtime_gw._connections.append(fake)
    try:
        await realtime_gw.broadcast_market_state({"enabled": False, "tickers": []})
    finally:
        realtime_gw._connections.remove(fake)

    assert len(sent) == 1
    payload = json.loads(sent[0])
    assert payload["type"] == "market_state"
    assert payload["data"]["enabled"] is False
    assert isinstance(payload["cursor"], int)
