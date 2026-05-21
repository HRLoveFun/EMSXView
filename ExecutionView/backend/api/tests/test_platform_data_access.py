"""Tests for logical data-domain adapters."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from platform_data.adapters import (
    CostViewAnalyticsAdapter,
    ExecutionHistoryAdapter,
    MarketReferenceDataAdapter,
    TcaFilters,
    TcaReport,
)


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
                "order_id": "1001", "route_id": "7", "fill_id": "F1",
                "order_as_of_date": "20260422", "source_date": "20260422",
                "local_fill_datetime": "2026-04-22T10:00:00",
                "exchange_exec_time": "10:00:00", "route_as_of_time": "09:45:00",
                "ny_fill_datetime": "2026-04-22T22:00:00",
                "broker": "BMTB", "strategy_type": "VWAP", "algo": "VWAP",
                "trader_name": "TRADER1", "exchange": "US", "side": "BUY",
                "equ_ticker": "AAPL US Equity", "ccy_ticker": "USD Curncy",
                "exec_type": "TRADE", "amount": 1000.0, "route_shares": 100.0,
                "fill_price": 189.25, "fill_shares": 100.0,
                "fetched_at": "2026-04-22T10:05:00",
            }
        ]

    def list_order_history(self, **kwargs):
        return [
            {
                "order_id": "1001", "order_as_of_date": "20260422",
                "equ_ticker": "AAPL US Equity", "side": "BUY",
                "route_count": 1, "fill_count": 1,
                "total_fill_shares": 100.0, "average_fill_price": 189.25,
                "first_fill_time": "2026-04-22T10:00:00",
                "last_fill_time": "2026-04-22T10:00:00",
            }
        ]

    def list_route_history(self, **kwargs):
        return [
            {
                "order_id": "1001", "route_id": "7",
                "order_as_of_date": "20260422",
                "broker": "BMTB", "algo": "VWAP", "trader_name": "TRADER1",
                "exchange": "US", "side": "BUY",
                "equ_ticker": "AAPL US Equity",
                "fill_count": 1, "total_fill_shares": 100.0,
                "average_fill_price": 189.25,
                "first_fill_time": "2026-04-22T10:00:00",
                "last_fill_time": "2026-04-22T10:00:00",
            }
        ]


def test_costview_analytics_adapter():
    analytics = CostViewAnalyticsAdapter(query_service_factory=_FakeTcaQueryService)
    report = analytics.build_tca_report(TcaFilters(order_ids=["5164591"], limit=5, offset=0))
    assert report.total_orders == 1
    assert report.filters["order_ids"] == ["5164591"]


def test_market_reference_adapter_latest_snapshot():
    market = MarketReferenceDataAdapter(daily_summary_db_factory=_FakeMarketDb)
    snapshot = market.get_market_snapshot(limit=10)
    assert snapshot.trade_date == "20260422"
    assert snapshot.row_count == 3
    assert snapshot.active_pool_id == "all"
    assert snapshot.rows[0].equ_ticker == "AAPL US Equity"


def test_market_reference_adapter_stock_pools_and_alerts():
    market = MarketReferenceDataAdapter(daily_summary_db_factory=_FakeMarketDb)
    snapshot = market.get_market_snapshot(
        limit=10, pool_id="volatility-watch",
        liquidity_alert="warning", sort_by="daily_volatility", sort_direction="desc",
    )
    assert snapshot.active_pool_id == "volatility-watch"
    assert snapshot.filters.liquidity_alert == "warning"
    assert snapshot.row_count == 1
    assert snapshot.rows[0].equ_ticker == "TSLA US Equity"
    assert snapshot.rows[0].volatility_alert == "critical"
    assert snapshot.candidate_payload.pool_id == "volatility-watch"


def test_execution_history_adapter():
    execution_history = ExecutionHistoryAdapter(service_factory=_FakeExecutionHistoryService)
    fill_history = execution_history.list_fill_history(limit=25, order_id="1001")
    order_history = execution_history.list_order_history(limit=25, order_id="1001")
    route_history = execution_history.list_route_history(limit=25, order_id="1001")
    assert fill_history.row_count == 1
    assert fill_history.rows[0].fill_id == "F1"
    assert order_history.row_count == 1
    assert order_history.rows[0].route_count == 1
    assert route_history.row_count == 1
    assert route_history.rows[0].route_id == "7"
