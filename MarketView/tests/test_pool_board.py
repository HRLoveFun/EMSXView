"""057 DL-29 — 固定筛选池池板端点测试。

覆盖：量价/难度/成本同屏、基线缺失显式 gap、未知池映射、鉴权。
策略：monkeypatch 路由模块级适配器与成本函数，不触真实库。
"""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config  # noqa: F401

from platform_data.contracts.market_contracts import MarketBaseline
from routers import pool_board


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "testsecret")


def _auth_headers() -> dict:
    token = jwt.encode({"sub": "u1", "role": "trader"}, "testsecret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _snapshot(pool_id: str = "all"):
    rows = [
        SimpleNamespace(
            equ_ticker="AAPL US Equity",
            daily_close=190.0,
            total_volume=1_000_000.0,
            adv_20d=2_000_000.0,
            volume_vs_adv20_pct=50.0,
            daily_volatility=2.1,
            intraday_volatility=1.4,
            liquidity_alert="none",
            volatility_alert="watch",
        ),
        SimpleNamespace(
            equ_ticker="MSFT US Equity",
            daily_close=410.0,
            total_volume=800_000.0,
            adv_20d=1_500_000.0,
            volume_vs_adv20_pct=53.3,
            daily_volatility=1.8,
            intraday_volatility=1.1,
            liquidity_alert="none",
            volatility_alert="none",
        ),
    ]
    return SimpleNamespace(trade_date="20260408", active_pool_id=pool_id, rows=rows)


class FakeMarket:
    def __init__(self, snapshot=None, error: Exception | None = None):
        self._snapshot = snapshot or _snapshot()
        self._error = error

    def get_market_snapshot(self, **_kwargs):
        if self._error:
            raise self._error
        return self._snapshot


class FakeBaseline:
    def __init__(self, items):
        self._items = items

    def get_baseline(self, tickers, connection_manager=None):
        return [item for item in self._items if item.equ_ticker in tickers]


class FakeSession:
    def market_code_for(self, exchange: str) -> str:
        return exchange or "US"

    def get_session(self, _market: str):
        return SimpleNamespace(market_open="09:30", market_close="16:00")


def _install(monkeypatch, market, baselines):
    monkeypatch.setattr(
        pool_board,
        "_adapters",
        lambda: (market, FakeBaseline(baselines), FakeSession()),
    )
    monkeypatch.setattr(pool_board, "ConnectionManager", lambda: object())
    monkeypatch.setattr(
        pool_board, "_cost_for", lambda *_args: (12.5, 3.2, True, "cost-model-v1", [])
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(pool_board.router)
    return TestClient(app)


def _baseline(ticker: str):
    return MarketBaseline(
        equ_ticker=ticker,
        as_of="20260407",
        log_volume_z=1.2,
        vol_percentile=78.0,
        intraday_vol_percentile=65.0,
        overnight_gap_sigma=None,
        auction_open_pct=None,
        auction_close_pct=None,
        adv5_adv60_ratio=1.1,
        spread_proxy_bps=None,
        n_days=45,
    )


def test_returns_rows_with_metrics_difficulty_and_cost(monkeypatch):
    _install(monkeypatch, FakeMarket(), [_baseline("AAPL US Equity")])
    response = _client().get(
        "/api/marketview/pool-board",
        params={"pool_id": "all", "limit": 40},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["row_count"] == 2
    assert payload["assumptions"]["notional_usd"] == 1_000_000
    aapl = payload["rows"][0]
    assert aapl["vol_percentile"] == 78.0
    assert aapl["expected_cost_bps"] == 12.5
    assert aapl["data_gaps"] == []
    # 无基线的行显式记 gap，不伪填分位
    msft = payload["rows"][1]
    assert msft["vol_percentile"] is None
    assert "baseline" in msft["data_gaps"]


def test_unknown_pool_maps_to_422(monkeypatch):
    _install(monkeypatch, FakeMarket(error=ValueError("Unknown market stock pool")), [])
    response = _client().get(
        "/api/marketview/pool-board",
        params={"pool_id": "nope"},
        headers=_auth_headers(),
    )
    assert response.status_code == 422


def test_requires_token(monkeypatch):
    _install(monkeypatch, FakeMarket(), [])
    response = _client().get("/api/marketview/pool-board")
    assert response.status_code == 401
