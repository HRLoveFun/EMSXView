from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, API_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from platform_data.adapters import (
    MarketAlert,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketDailySnapshotRow,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
)
from routers import marketview as marketview_router_module


class _FakeMarketAdapter:
    def get_market_snapshot(self, **kwargs):
        pool_id = kwargs.get("pool_id", "all")
        if pool_id == "bad-pool":
            raise ValueError("Unknown market stock pool: bad-pool")

        filters = MarketSnapshotFilters(
            min_adv_20d=kwargs.get("min_adv_20d"),
            min_total_volume=kwargs.get("min_total_volume"),
            min_daily_volatility=kwargs.get("min_daily_volatility"),
            min_intraday_volatility=kwargs.get("min_intraday_volatility"),
            liquidity_alert=kwargs.get("liquidity_alert", "all"),
            volatility_alert=kwargs.get("volatility_alert", "all"),
        )
        sort = MarketSnapshotSort(
            field=kwargs.get("sort_by", "total_volume"),
            direction=kwargs.get("sort_direction", "desc"),
        )
        pools = [
            MarketStockPool(
                pool_id="all",
                label="Full Snapshot",
                description="Latest Stage 7 universe for the selected trade date.",
            ),
            MarketStockPool(
                pool_id="volatility-watch",
                label="Volatility Watch",
                description="Names with elevated daily or intraday volatility for gap-risk review.",
                default_sort_by="daily_volatility",
            ),
        ]
        alerts = [
            MarketAlert(
                code="volatility-alert",
                category="volatility",
                severity="critical",
                message="Daily vol 45.2%, intraday vol 4.1%",
            )
        ]
        rows = [
            MarketDailySnapshotRow(
                equ_ticker="TSLA US Equity",
                trade_date="20260422",
                daily_close=166.8,
                daily_volatility=45.2,
                intraday_volatility=4.1,
                total_volume=25_000_000,
                adv_5d=12_000_000,
                adv_20d=8_000_000,
                volume_vs_adv20_pct=312.5,
                liquidity_alert="warning",
                volatility_alert="critical",
                alert_count=2,
                alerts=alerts,
            )
        ]
        return MarketSnapshot(
            trade_date="20260422",
            row_count=1,
            available_pools=pools,
            active_pool_id=pool_id,
            filters=filters,
            sort=sort,
            rows=rows,
            candidate_payload=MarketCandidatePayload(
                source="marketview-candidate-v1",
                handoff_target="ExecutionView",
                trade_date="20260422",
                pool_id=pool_id,
                pool_label="Volatility Watch",
                filters=filters,
                sort=sort,
                row_count=1,
                candidates=[
                    MarketCandidateRow(
                        equ_ticker="TSLA US Equity",
                        trade_date="20260422",
                        daily_close=166.8,
                        total_volume=25_000_000,
                        adv_20d=8_000_000,
                        daily_volatility=45.2,
                        intraday_volatility=4.1,
                        liquidity_alert="warning",
                        volatility_alert="critical",
                        alerts=alerts,
                    )
                ],
            ),
        )


def _build_client(monkeypatch) -> TestClient:
    app = FastAPI()
    monkeypatch.setattr(
        marketview_router_module,
        "platform_data",
        SimpleNamespace(market=_FakeMarketAdapter()),
    )
    app.include_router(marketview_router_module.router)
    return TestClient(app)


def test_marketview_router_returns_stock_pool_snapshot(monkeypatch):
    client = _build_client(monkeypatch)

    response = client.get(
        "/api/marketview/snapshot",
        params={
            "pool_id": "volatility-watch",
            "sort_by": "daily_volatility",
            "sort_direction": "desc",
            "liquidity_alert": "warning",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["active_pool_id"] == "volatility-watch"
    assert body["data"]["rows"][0]["equ_ticker"] == "TSLA US Equity"
    assert body["data"]["rows"][0]["alerts"][0]["category"] == "volatility"
    assert body["data"]["candidate_payload"]["source"] == "marketview-candidate-v1"
    assert body["data"]["candidate_payload"]["candidates"][0]["equ_ticker"] == "TSLA US Equity"


def test_marketview_router_rejects_unknown_stock_pool(monkeypatch):
    client = _build_client(monkeypatch)

    response = client.get("/api/marketview/snapshot", params={"pool_id": "bad-pool"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown market stock pool: bad-pool"