"""Data Transfer Objects for the CostView database subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class AttributionRowDTO:
    order_id: str
    route_id: str
    fill_id: str
    order_as_of_date_iso: str
    config_version: str
    market_code: str
    broker: str
    algo: str
    side: int
    fill_shares: float
    fill_price: float
    route_shares: Optional[float]
    pct_adv: Optional[float]
    participation_rate: Optional[float]
    arrival_px: Optional[float]
    interval_vwap: Optional[float]
    mid_at_fill: Optional[float]
    mid_fill_plus_1m: Optional[float]
    mid_fill_plus_5m: Optional[float]
    mid_fill_plus_30m: Optional[float]
    is_bps: Optional[float]
    vwap_bps: Optional[float]
    reversal_1m_bps: Optional[float]
    reversal_5m_bps: Optional[float]
    reversal_30m_bps: Optional[float]
    data_quality_flags: int
    source_version: str
    ingested_at: str


@dataclass(frozen=True)
class AttributionConfigDTO:
    version_id: str
    bench_methods: List[str]
    reversal_windows_min: List[int]
    winsor_pct: float
    adv_window_days: int
    bootstrap_n: int
    min_cell_n: int
    description: Optional[str]


@dataclass(frozen=True)
class PipelineRunDTO:
    stage_name: str
    run_started_at: str
    status: str
    target_start_date: str
    target_end_date: str
    config_version: str
    schema_version: int


@dataclass(frozen=True)
class PipelineRunResultDTO:
    run_id: int
    run_finished_at: str
    status: str
    rows_written: int
    rows_updated: int
    error_message: Optional[str]
    duration_sec: float


@dataclass(frozen=True)
class FillMetricsQueryDTO:
    start_date_iso: str
    end_date_iso: str
    config_version: Optional[str] = None
    regime_dim: Optional[str] = None
