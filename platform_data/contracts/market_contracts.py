"""Market-view data contracts — pure dataclasses with no business logic.

Ownership: CostView market-data pipeline publishes these contracts.
Consumers: MarketView, ExecutionView (handoff).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketAlert:
    code: str
    category: str  # "liquidity" | "volatility"
    severity: str  # "normal" | "warning" | "critical"
    message: str


@dataclass(frozen=True)
class MarketStockPool:
    pool_id: str
    label: str
    description: str
    default_sort_by: str = "total_volume"
    default_sort_direction: str = "desc"


@dataclass(frozen=True)
class MarketSnapshotFilters:
    min_adv_20d: float | None = None
    min_total_volume: float | None = None
    min_daily_volatility: float | None = None
    min_intraday_volatility: float | None = None
    liquidity_alert: str = "all"
    volatility_alert: str = "all"


@dataclass(frozen=True)
class MarketSnapshotSort:
    field: str = "total_volume"
    direction: str = "desc"


@dataclass(frozen=True)
class MarketDailySnapshotRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    total_volume: float | None
    adv_5d: float | None
    adv_20d: float | None
    volume_vs_adv20_pct: float | None = None
    liquidity_alert: str = "none"
    volatility_alert: str = "none"
    alert_count: int = 0
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidateRow:
    equ_ticker: str
    trade_date: str
    daily_close: float | None
    total_volume: float | None
    adv_20d: float | None
    daily_volatility: float | None
    intraday_volatility: float | None
    liquidity_alert: str
    volatility_alert: str
    alerts: list[MarketAlert] = field(default_factory=list)


@dataclass(frozen=True)
class MarketCandidatePayload:
    source: str
    handoff_target: str
    trade_date: str | None
    pool_id: str
    pool_label: str | None
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    row_count: int
    candidates: list[MarketCandidateRow]


@dataclass(frozen=True)
class MarketSnapshot:
    trade_date: str | None
    row_count: int
    available_pools: list[MarketStockPool]
    active_pool_id: str
    filters: MarketSnapshotFilters
    sort: MarketSnapshotSort
    rows: list[MarketDailySnapshotRow]
    candidate_payload: MarketCandidatePayload
