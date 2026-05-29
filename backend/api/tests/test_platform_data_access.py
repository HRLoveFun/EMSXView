"""Tests for logical data-domain adapters.

Phase 7: Removed sys.path.insert(PROJECT_ROOT) hack — platform_data is now
installed as an editable package (pip install -e platform_data).
"""

from platform_data.adapters import (
    MarketReferenceDataAdapter,
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


def test_market_reference_adapter_latest_snapshot():
    market = MarketReferenceDataAdapter(_reader=_FakeMarketDb())
    snapshot = market.get_market_snapshot(limit=10)
    assert snapshot.trade_date == "20260422"
    assert snapshot.row_count == 3
    assert snapshot.active_pool_id == "all"
    assert snapshot.rows[0].equ_ticker == "AAPL US Equity"


def test_market_reference_adapter_stock_pools_and_alerts():
    market = MarketReferenceDataAdapter(_reader=_FakeMarketDb())
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
