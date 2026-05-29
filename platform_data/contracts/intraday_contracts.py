"""Intraday-feature data contracts — pure dataclasses with no business logic.

Ownership: CostView market-data pipeline publishes these contracts.
Consumers: MarketView intraday feature analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field


INTRADAY_BUCKET_OPTIONS: tuple[int, ...] = (5, 10, 15, 30, 60)
INTRADAY_DEFAULT_BUCKET_MINUTES: int = 30
INTRADAY_MAX_TICKERS: int = 25


@dataclass(frozen=True)
class IntradayFeatureBucket:
    bucket_start: str
    bucket_end: str
    bar_count: int
    volume: float | None
    cumulative_volume: float | None
    cumulative_volume_pct: float | None
    vwap: float | None
    close: float | None
    high: float | None
    low: float | None
    realized_vol_annualized: float | None
    volume_vs_adv20_pct: float | None


@dataclass(frozen=True)
class IntradayTickerFeatures:
    equ_ticker: str
    trade_date: str
    bar_count: int
    first_bar_time: str | None
    last_bar_time: str | None
    total_volume: float | None
    daily_vwap: float | None
    daily_close: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    adv_20d: float | None
    open_window_volume: float | None
    open_window_vwap: float | None
    open_window_share_pct: float | None
    close_window_volume: float | None
    close_window_vwap: float | None
    close_window_share_pct: float | None
    volume_vs_adv20_pct: float | None
    buckets: list[IntradayFeatureBucket] = field(default_factory=list)


@dataclass(frozen=True)
class IntradayFeatureSnapshot:
    trade_date: str | None
    bucket_minutes: int
    ticker_count: int
    missing_tickers: list[str]
    tickers: list[IntradayTickerFeatures]
