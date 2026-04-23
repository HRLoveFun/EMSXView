"""Tests for unified logical data-domain adapters."""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from platform_data import TcaFilters, TcaReport, build_platform_data_access


class _FakeRepositoryProvider:
    def __init__(self):
        self.is_active = True

    async def load_orders(self, limit: int = 5000):
        return [{"kind": "order", "limit": limit}]

    async def load_routes(self, limit: int = 10000):
        return [{"kind": "route", "limit": limit}]

    async def persist_order(self, **kwargs):
        return kwargs.get("order_id") == "A1"

    async def persist_route(self, **kwargs):
        return kwargs.get("route_id") == 7

    async def persist_audit_event(self, **kwargs):
        return kwargs.get("action") == "TEST"


class _FakeTcaQueryService:
    def build_tca_report(self, filters: TcaFilters) -> TcaReport:
        return TcaReport(
            filters={"order_ids": filters.order_ids or []},
            total_orders=1,
            offset=filters.offset,
            limit=filters.limit,
            orders=[],
        )


class _FakeMarketDb:
    def get_latest_daily_summary(self, limit: int = 25, trade_date: str | None = None):
        import pandas as pd

        resolved_date = trade_date or "20260422"
        return pd.DataFrame(
            [
                {
                    "equ_ticker": "AAPL US Equity",
                    "trade_date": resolved_date,
                    "daily_close": 189.25,
                    "daily_volatility": 22.4,
                    "intraday_volatility": 18.1,
                    "total_volume": 105000000,
                    "adv_5d": 99000000,
                    "adv_20d": 101500000,
                }
            ]
        )


def test_build_platform_data_access_without_operational_provider():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        query_service_factory=_FakeTcaQueryService,
    )
    assert access.operational is None
    assert access.analytics.describe()["domain"] == "costview-analytics"
    assert access.market.describe()["domain"] == "market-reference"


def test_execution_operational_adapter_forwards_provider_calls():
    access = build_platform_data_access(
        _FakeRepositoryProvider(),
        market_db_factory=_FakeMarketDb,
        query_service_factory=_FakeTcaQueryService,
    )

    assert access.operational is not None
    assert access.operational.is_active is True
    assert asyncio.run(access.operational.load_orders(limit=25)) == [{"kind": "order", "limit": 25}]
    assert asyncio.run(access.operational.load_routes(limit=12)) == [{"kind": "route", "limit": 12}]
    assert asyncio.run(access.operational.persist_order(order_id="A1")) is True
    assert asyncio.run(access.operational.persist_route(route_id=7)) is True
    assert asyncio.run(access.operational.persist_audit_event(action="TEST")) is True


def test_costview_analytics_adapter_exposes_single_entrypoint():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        query_service_factory=_FakeTcaQueryService,
    )
    report = access.analytics.build_tca_report(TcaFilters(order_ids=["5164591"], limit=5, offset=0))

    assert report.total_orders == 1
    assert report.filters["order_ids"] == ["5164591"]


def test_market_reference_adapter_exposes_latest_snapshot():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        query_service_factory=_FakeTcaQueryService,
    )
    snapshot = access.market.get_market_snapshot(limit=10)

    assert snapshot.trade_date == "20260422"
    assert snapshot.row_count == 1
    assert snapshot.rows[0].equ_ticker == "AAPL US Equity"
    assert snapshot.rows[0].adv_20d == 101500000