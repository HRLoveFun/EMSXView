"""057 DL-10：日度基线端点测试（MarketView standalone 路由）。

策略与 test_marketview_router.py 一致：TestClient + monkeypatch 替换
路由模块级 `_baseline` 单例为 fake adapter（不连真实库）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# conftest 已设置 sys.path；import 顺序与 main.py 保持一致
import config  # noqa: F401
from routers import baseline
from platform_data.contracts import MarketBaseline

TICKER = "SEC_A US Equity"


def _fake_baseline(ticker: str = TICKER, **overrides) -> MarketBaseline:
    base = dict(
        equ_ticker=ticker,
        as_of="20260925",
        log_volume_z=1.234,
        vol_percentile=88.0,
        intraday_vol_percentile=60.0,
        overnight_gap_sigma=0.5,
        auction_open_pct=5.0,
        auction_close_pct=12.0,
        adv5_adv60_ratio=0.95,
        spread_proxy_bps=42.0,
        n_days=60,
        excluded_dates=(),
    )
    base.update(overrides)
    return MarketBaseline(**base)


class _FakeAdapter:
    def __init__(self, baselines=None, error=None):
        self.baselines = baselines if baselines is not None else [_fake_baseline()]
        self.error = error
        self.calls: list[dict] = []

    def get_baseline(self, tickers, *, as_of=None, exclude_dates=()):
        self.calls.append({"tickers": list(tickers), "as_of": as_of})
        if self.error is not None:
            raise self.error
        return self.baselines


def _build_client(adapter: _FakeAdapter) -> TestClient:
    app = FastAPI()
    app.include_router(baseline.router)
    baseline._baseline = adapter
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_singleton():
    yield
    baseline._baseline = None


class TestDailyBaselineEndpoint:
    def test_returns_serialized_baselines(self):
        client = _build_client(_FakeAdapter())

        response = client.get("/api/marketview/daily-baseline", params={"tickers": TICKER})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["window_days"] == 60
        assert data["schema_version"] == "market-baseline-v1"
        assert data["as_of"] == "20260925"
        b = data["baselines"][0]
        assert b["equ_ticker"] == TICKER
        assert b["log_volume_z"] == 1.234
        assert b["auction_close_pct"] == 12.0
        assert b["n_days"] == 60
        assert "1 with data" in body["message"]

    def test_forwards_as_of_and_reports_no_data(self):
        client = _build_client(
            _FakeAdapter(
                baselines=[
                    _fake_baseline(
                        n_days=0,
                        as_of="",
                        log_volume_z=None,
                        vol_percentile=None,
                        intraday_vol_percentile=None,
                        overnight_gap_sigma=None,
                        auction_open_pct=None,
                        auction_close_pct=None,
                        adv5_adv60_ratio=None,
                        spread_proxy_bps=None,
                    )
                ]
            )
        )

        response = client.get(
            "/api/marketview/daily-baseline",
            params={"tickers": TICKER, "as_of": "20260925"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["baselines"][0]["n_days"] == 0
        assert body["data"]["baselines"][0]["log_volume_z"] is None
        assert "0 with data" in body["message"]

    def test_rejects_empty_tickers(self):
        client = _build_client(_FakeAdapter())

        response = client.get("/api/marketview/daily-baseline", params={"tickers": " , "})

        assert response.status_code == 400
        assert "at least one" in response.json()["detail"]

    def test_maps_unexpected_error_to_500(self):
        client = _build_client(_FakeAdapter(error=RuntimeError("db down")))

        response = client.get("/api/marketview/daily-baseline", params={"tickers": TICKER})

        assert response.status_code == 500
