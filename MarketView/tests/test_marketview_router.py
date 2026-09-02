"""MarketView standalone 路由测试。

覆盖三个端点：
- GET  /api/marketview/snapshot
- GET  /api/marketview/intraday-features
- POST /api/marketview/handoff/execution

策略：monkeypatch 路由模块级 `_market` 单例为 fake adapter，
handoff 使用真实的内存 HandoffExchangeAdapter（无 Redis / 数据库依赖）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# conftest 已设置 sys.path；import 顺序与 main.py 保持一致（config 先于 platform_data）
import config  # noqa: F401
from routers import marketview
from platform_data.adapters import HandoffExchangeAdapter
from platform_data.contracts.market_contracts import (
    MarketAlert,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketDailySnapshotRow,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
)
from platform_data.contracts.intraday_contracts import (
    IntradayFeatureBucket,
    IntradayFeatureSnapshot,
    IntradayTickerFeatures,
)

TRADE_DATE = "20260902"


def _build_snapshot() -> MarketSnapshot:
    """构造一份带两个候选的最小快照数据。"""
    alert = MarketAlert(
        code="liquidity-alert",
        category="liquidity",
        severity="warning",
        message="Total volume below ADV20 threshold",
    )
    filters = MarketSnapshotFilters()
    sort = MarketSnapshotSort()
    candidate_payload = MarketCandidatePayload(
        source="marketview-candidate-v1",
        handoff_target="ExecutionView",
        trade_date=TRADE_DATE,
        pool_id="all",
        pool_label="Full Snapshot",
        filters=filters,
        sort=sort,
        row_count=2,
        candidates=[
            MarketCandidateRow(
                equ_ticker="AAPL US Equity",
                trade_date=TRADE_DATE,
                daily_close=189.25,
                total_volume=105_000_000,
                adv_20d=101_500_000,
                daily_volatility=22.4,
                intraday_volatility=1.8,
                liquidity_alert="normal",
                volatility_alert="normal",
            ),
            MarketCandidateRow(
                equ_ticker="TSLA US Equity",
                trade_date=TRADE_DATE,
                daily_close=166.8,
                total_volume=25_000_000,
                adv_20d=8_000_000,
                daily_volatility=45.2,
                intraday_volatility=4.1,
                liquidity_alert="warning",
                volatility_alert="critical",
                alerts=[alert],
            ),
        ],
    )
    return MarketSnapshot(
        trade_date=TRADE_DATE,
        row_count=1,
        available_pools=[
            MarketStockPool(pool_id="all", label="Full Snapshot", description="Latest universe")
        ],
        active_pool_id="all",
        filters=filters,
        sort=sort,
        rows=[
            MarketDailySnapshotRow(
                equ_ticker="AAPL US Equity",
                trade_date=TRADE_DATE,
                daily_close=189.25,
                daily_volatility=22.4,
                intraday_volatility=1.8,
                total_volume=105_000_000,
                adv_5d=99_000_000,
                adv_20d=101_500_000,
                volume_vs_adv20_pct=103.45,
                liquidity_alert="normal",
                volatility_alert="normal",
            ),
        ],
        candidate_payload=candidate_payload,
    )


def _build_intraday(bucket_minutes: int) -> IntradayFeatureSnapshot:
    """构造单 ticker 的日内特征快照。"""
    bucket = IntradayFeatureBucket(
        bucket_start="09:30",
        bucket_end="10:00",
        bar_count=2,
        volume=1_000_000.0,
        cumulative_volume=1_000_000.0,
        cumulative_volume_pct=9.5,
        vwap=188.9,
        close=189.1,
        high=189.5,
        low=188.4,
        realized_vol_annualized=18.2,
        volume_vs_adv20_pct=9.85,
    )
    ticker = IntradayTickerFeatures(
        equ_ticker="AAPL US Equity",
        trade_date=TRADE_DATE,
        bar_count=13,
        first_bar_time="09:30",
        last_bar_time="16:00",
        total_volume=10_500_000.0,
        daily_vwap=189.0,
        daily_close=189.25,
        daily_volatility=22.4,
        intraday_volatility=1.8,
        adv_20d=101_500_000.0,
        open_window_volume=1_000_000.0,
        open_window_vwap=188.9,
        open_window_share_pct=9.5,
        close_window_volume=1_100_000.0,
        close_window_vwap=189.3,
        close_window_share_pct=10.5,
        volume_vs_adv20_pct=10.34,
        buckets=[bucket],
    )
    return IntradayFeatureSnapshot(
        trade_date=TRADE_DATE,
        bucket_minutes=bucket_minutes,
        ticker_count=1,
        missing_tickers=[],
        tickers=[ticker],
    )


class _FakeMarketAdapter:
    """替身 adapter：返回预置快照 / 日内特征，或抛出指定异常。"""

    def __init__(
        self,
        snapshot: MarketSnapshot | None = None,
        intraday: IntradayFeatureSnapshot | None = None,
        snapshot_error: Exception | None = None,
    ) -> None:
        self.snapshot = snapshot or _build_snapshot()
        self.intraday = intraday
        self.snapshot_error = snapshot_error
        self.snapshot_calls: list[dict] = []
        self.intraday_calls: list[dict] = []

    def get_market_snapshot(self, **kwargs):
        self.snapshot_calls.append(kwargs)
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return self.snapshot

    def get_intraday_features(self, *, equ_tickers, trade_date=None, bucket_minutes=30):
        self.intraday_calls.append(
            {
                "equ_tickers": list(equ_tickers),
                "trade_date": trade_date,
                "bucket_minutes": bucket_minutes,
            }
        )
        if self.intraday is None:
            return IntradayFeatureSnapshot(
                trade_date=None,
                bucket_minutes=bucket_minutes,
                ticker_count=0,
                missing_tickers=list(equ_tickers),
                tickers=[],
            )
        return self.intraday


def _build_client(adapter: _FakeMarketAdapter) -> TestClient:
    app = FastAPI()
    app.include_router(marketview.router)
    marketview._market = adapter
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_market_singleton():
    """每个用例结束后清理模块级单例，避免用例间串扰。"""
    yield
    marketview._market = None


class TestSnapshotEndpoint:
    def test_returns_envelope_with_rows_and_candidate_payload(self):
        client = _build_client(_FakeMarketAdapter())

        response = client.get("/api/marketview/snapshot")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["trade_date"] == TRADE_DATE
        assert body["data"]["row_count"] == 1
        assert body["data"]["available_pools"][0]["pool_id"] == "all"
        assert body["data"]["candidate_payload"]["row_count"] == 2

    def test_forwards_query_filters_to_adapter(self):
        adapter = _FakeMarketAdapter()
        client = _build_client(adapter)

        client.get(
            "/api/marketview/snapshot",
            params={
                "limit": 10,
                "trade_date": TRADE_DATE,
                "pool_id": "all",
                "min_adv_20d": 5_000_000,
                "liquidity_alert": "warning",
                "sort_by": "adv_20d",
                "sort_direction": "asc",
            },
        )

        call = adapter.snapshot_calls[0]
        assert call["limit"] == 10
        assert call["trade_date"] == TRADE_DATE
        assert call["min_adv_20d"] == 5_000_000
        assert call["liquidity_alert"] == "warning"
        assert call["sort_by"] == "adv_20d"
        assert call["sort_direction"] == "asc"

    def test_maps_value_error_to_400(self):
        client = _build_client(_FakeMarketAdapter(snapshot_error=ValueError("unknown pool")))

        response = client.get("/api/marketview/snapshot")

        assert response.status_code == 400
        assert "unknown pool" in response.json()["detail"]

    def test_maps_unexpected_error_to_500(self):
        client = _build_client(_FakeMarketAdapter(snapshot_error=RuntimeError("db down")))

        response = client.get("/api/marketview/snapshot")

        assert response.status_code == 500


class TestIntradayFeaturesEndpoint:
    def test_returns_serialized_ticker_features(self):
        client = _build_client(_FakeMarketAdapter(intraday=_build_intraday(30)))

        response = client.get(
            "/api/marketview/intraday-features",
            params={"tickers": "AAPL US Equity", "trade_date": TRADE_DATE, "bucket_minutes": 30},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["ticker_count"] == 1
        ticker = body["data"]["tickers"][0]
        assert ticker["equ_ticker"] == "AAPL US Equity"
        assert ticker["buckets"][0]["bucket_start"] == "09:30"

    def test_reports_missing_tickers_when_no_bars(self):
        client = _build_client(_FakeMarketAdapter(intraday=None))

        response = client.get(
            "/api/marketview/intraday-features",
            params={"tickers": "AAPL US Equity"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["trade_date"] is None
        assert body["data"]["missing_tickers"] == ["AAPL US Equity"]

    def test_rejects_unsupported_bucket_minutes(self):
        client = _build_client(_FakeMarketAdapter())

        response = client.get(
            "/api/marketview/intraday-features",
            params={"tickers": "AAPL US Equity", "bucket_minutes": 7},
        )

        assert response.status_code == 400
        assert "Unsupported bucket_minutes" in response.json()["detail"]

    def test_rejects_empty_tickers(self):
        client = _build_client(_FakeMarketAdapter())

        response = client.get("/api/marketview/intraday-features", params={"tickers": " , "})

        assert response.status_code == 400
        assert "at least one" in response.json()["detail"]

    def test_rejects_more_than_max_tickers(self):
        client = _build_client(_FakeMarketAdapter())
        too_many = ",".join(f"T{i}" for i in range(marketview.INTRADAY_MAX_TICKERS + 1))

        response = client.get("/api/marketview/intraday-features", params={"tickers": too_many})

        assert response.status_code == 400
        assert "Too many tickers" in response.json()["detail"]


class TestHandoffEndpoint:
    def test_publishes_candidates_to_execution_view(self):
        client = _build_client(_FakeMarketAdapter())
        exchange = HandoffExchangeAdapter()

        import platform_data

        original = platform_data.get_shared_handoff_exchange
        platform_data.get_shared_handoff_exchange = lambda: exchange
        try:
            response = client.post(
                "/api/marketview/handoff/execution",
                json={"pool_id": "all", "trade_date": TRADE_DATE, "limit": 40},
            )
        finally:
            platform_data.get_shared_handoff_exchange = original

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["metadata"]["source"] == "MarketView"
        assert body["data"]["metadata"]["handoff_target"] == "ExecutionView"
        assert body["data"]["candidate_payload"]["row_count"] == 2

        stored = exchange.get_market_to_execution()
        assert stored is not None
        assert stored.candidate_payload.row_count == 2

    def test_narrows_candidates_to_requested_tickers(self):
        client = _build_client(_FakeMarketAdapter())
        exchange = HandoffExchangeAdapter()

        import platform_data

        original = platform_data.get_shared_handoff_exchange
        platform_data.get_shared_handoff_exchange = lambda: exchange
        try:
            response = client.post(
                "/api/marketview/handoff/execution",
                json={"pool_id": "all", "tickers": ["TSLA US Equity"]},
            )
        finally:
            platform_data.get_shared_handoff_exchange = original

        assert response.status_code == 200
        payload = response.json()["data"]["candidate_payload"]
        assert payload["row_count"] == 1
        assert payload["candidates"][0]["equ_ticker"] == "TSLA US Equity"
        assert "trace_id" in response.json()["data"]["metadata"]

    def test_rejects_unknown_pool_with_400(self):
        client = _build_client(_FakeMarketAdapter(snapshot_error=ValueError("unknown pool")))

        response = client.post(
            "/api/marketview/handoff/execution",
            json={"pool_id": "nope"},
        )

        assert response.status_code == 400
