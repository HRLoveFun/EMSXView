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
    def _build_frame(self, trade_date: str | None):
        import pandas as pd

        resolved_date = trade_date or "20260422"
        return pd.DataFrame(
            [
                {
                    "equ_ticker": "AAPL US Equity",
                    "trade_date": resolved_date,
                    "daily_close": 189.25,
                    "daily_volatility": 22.4,
                    "intraday_volatility": 1.8,
                    "total_volume": 105000000,
                    "adv_5d": 99000000,
                    "adv_20d": 101500000,
                },
                {
                    "equ_ticker": "TSLA US Equity",
                    "trade_date": resolved_date,
                    "daily_close": 166.8,
                    "daily_volatility": 45.2,
                    "intraday_volatility": 4.1,
                    "total_volume": 25000000,
                    "adv_5d": 12000000,
                    "adv_20d": 8000000,
                },
                {
                    "equ_ticker": "ZM US Equity",
                    "trade_date": resolved_date,
                    "daily_close": 58.9,
                    "daily_volatility": 18.0,
                    "intraday_volatility": 1.2,
                    "total_volume": 1500000,
                    "adv_5d": 3000000,
                    "adv_20d": 4000000,
                },
            ]
        )

    def get_latest_daily_summary(self, limit: int = 25, trade_date: str | None = None):
        return self._build_frame(trade_date).head(limit)

    def get_trade_date_daily_summary(self, trade_date: str | None = None):
        return self._build_frame(trade_date)


class _FakeExecutionHistoryService:
    def list_fill_history(self, **kwargs):
        return [
            {
                "order_id": "1001",
                "route_id": "7",
                "fill_id": "F1",
                "order_as_of_date": "20260422",
                "source_date": "20260422",
                "local_fill_datetime": "2026-04-22T10:00:00",
                "exchange_exec_time": "10:00:00",
                "route_as_of_time": "09:45:00",
                "ny_fill_datetime": "2026-04-22T22:00:00",
                "broker": "BMTB",
                "strategy_type": "VWAP",
                "algo": "VWAP",
                "trader_name": "TRADER1",
                "exchange": "US",
                "side": "BUY",
                "equ_ticker": "AAPL US Equity",
                "ccy_ticker": "USD Curncy",
                "exec_type": "TRADE",
                "amount": 1000.0,
                "route_shares": 100.0,
                "fill_price": 189.25,
                "fill_shares": 100.0,
                "fetched_at": "2026-04-22T10:05:00",
            }
        ]

    def list_order_history(self, **kwargs):
        return [
            {
                "order_id": "1001",
                "order_as_of_date": "20260422",
                "equ_ticker": "AAPL US Equity",
                "side": "BUY",
                "route_count": 1,
                "fill_count": 1,
                "total_fill_shares": 100.0,
                "average_fill_price": 189.25,
                "first_fill_time": "2026-04-22T10:00:00",
                "last_fill_time": "2026-04-22T10:00:00",
            }
        ]

    def list_route_history(self, **kwargs):
        return [
            {
                "order_id": "1001",
                "route_id": "7",
                "order_as_of_date": "20260422",
                "broker": "BMTB",
                "algo": "VWAP",
                "trader_name": "TRADER1",
                "exchange": "US",
                "side": "BUY",
                "equ_ticker": "AAPL US Equity",
                "fill_count": 1,
                "total_fill_shares": 100.0,
                "average_fill_price": 189.25,
                "first_fill_time": "2026-04-22T10:00:00",
                "last_fill_time": "2026-04-22T10:00:00",
            }
        ]


def test_build_platform_data_access_without_operational_provider():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )
    assert access.live_execution is None
    assert access.operational is None
    assert access.execution_history.describe()["domain"] == "execution-history"
    assert access.analytics.describe()["domain"] == "costview-analytics"
    assert access.market.describe()["domain"] == "market-reference"


def test_execution_operational_adapter_forwards_provider_calls():
    access = build_platform_data_access(
        _FakeRepositoryProvider(),
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )

    assert access.live_execution is access.operational
    assert access.live_execution is not None
    assert access.operational is not None
    assert access.operational.is_active is True
    assert access.live_execution.is_active is True
    assert asyncio.run(access.operational.load_orders(limit=25)) == [{"kind": "order", "limit": 25}]
    assert asyncio.run(access.operational.load_routes(limit=12)) == [{"kind": "route", "limit": 12}]
    assert asyncio.run(access.operational.persist_order(order_id="A1")) is True
    assert asyncio.run(access.operational.persist_route(route_id=7)) is True
    assert asyncio.run(access.operational.persist_audit_event(action="TEST")) is True


def test_costview_analytics_adapter_exposes_single_entrypoint():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )
    report = access.analytics.build_tca_report(TcaFilters(order_ids=["5164591"], limit=5, offset=0))

    assert report.total_orders == 1
    assert report.filters["order_ids"] == ["5164591"]


def test_market_reference_adapter_exposes_latest_snapshot():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )
    snapshot = access.market.get_market_snapshot(limit=10)

    assert snapshot.trade_date == "20260422"
    assert snapshot.row_count == 3
    assert snapshot.active_pool_id == "all"
    assert snapshot.rows[0].equ_ticker == "AAPL US Equity"
    assert snapshot.rows[0].adv_20d == 101500000
    assert snapshot.rows[0].liquidity_alert == "normal"
    assert snapshot.candidate_payload.source == "marketview-candidate-v1"
    assert snapshot.candidate_payload.handoff_target == "ExecutionView"
    assert len(snapshot.available_pools) == 4


def test_market_reference_adapter_supports_stock_pools_alerts_and_handoff_contract():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )

    snapshot = access.market.get_market_snapshot(
        limit=10,
        pool_id="volatility-watch",
        liquidity_alert="warning",
        sort_by="daily_volatility",
        sort_direction="desc",
    )

    assert snapshot.trade_date == "20260422"
    assert snapshot.active_pool_id == "volatility-watch"
    assert snapshot.filters.liquidity_alert == "warning"
    assert snapshot.sort.field == "daily_volatility"
    assert snapshot.row_count == 1
    assert snapshot.rows[0].equ_ticker == "TSLA US Equity"
    assert snapshot.rows[0].liquidity_alert == "warning"
    assert snapshot.rows[0].volatility_alert == "critical"
    assert snapshot.rows[0].volume_vs_adv20_pct == 312.5
    assert snapshot.rows[0].alert_count == 2
    assert len(snapshot.rows[0].alerts) == 2
    assert snapshot.candidate_payload.pool_id == "volatility-watch"
    assert snapshot.candidate_payload.pool_label == "Volatility Watch"
    assert snapshot.candidate_payload.row_count == 1
    assert snapshot.candidate_payload.candidates[0].equ_ticker == "TSLA US Equity"


def test_execution_history_adapter_exposes_fill_order_and_route_views():
    access = build_platform_data_access(
        market_db_factory=_FakeMarketDb,
        execution_history_service_factory=_FakeExecutionHistoryService,
        query_service_factory=_FakeTcaQueryService,
    )

    fill_history = access.execution_history.list_fill_history(limit=25, order_id="1001")
    order_history = access.execution_history.list_order_history(limit=25, order_id="1001")
    route_history = access.execution_history.list_route_history(limit=25, order_id="1001")

    assert fill_history.row_count == 1
    assert fill_history.rows[0].fill_id == "F1"
    assert fill_history.rows[0].equ_ticker == "AAPL US Equity"
    assert order_history.row_count == 1
    assert order_history.rows[0].route_count == 1
    assert route_history.row_count == 1
    assert route_history.rows[0].route_id == "7"