"""Data Transfer Objects for the CostView database subsystem.

Pure data containers with no DB knowledge. These act as the contract
between the business logic layer and the data access layer (repositories).

Phase 1: define core DTOs for cross-database operations.
Phase 2: expand with specific DTOs for each repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# Connection management DTOs
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DatabaseInfo:
    """Metadata about a single CostView database."""
    name: str           # e.g. "raw_fills", "processed_fills"
    path: Path
    exists: bool
    size_bytes: Optional[int] = None
    table_count: Optional[int] = None


@dataclass(frozen=True)
class DatabaseRegistry:
    """Snapshot of all registered databases."""
    databases: List[DatabaseInfo]
    config_root: Path


# ═══════════════════════════════════════════════════════════════════════════
# Regime distribution DTOs (used by costview.py router)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RegimeDistributionRow:
    """One row of regime distribution data per (date, market_code)."""
    date: str
    market_code: str
    low: int = 0
    normal: int = 0
    high: int = 0
    extreme: int = 0
    none_count: int = 0
    total: int = 0


@dataclass(frozen=True)
class RegimeDistributionResult:
    """Result of a regime distribution query."""
    rows: List[RegimeDistributionRow]
    regime_dim: str
    config_version: Optional[str] = None
    start_date: str = ""
    end_date: str = ""


# ═══════════════════════════════════════════════════════════════════════════
# Processing status DTOs (used by pipeline status queries)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DatabaseStatus:
    """Status of a single database in the pipeline."""
    name: str
    total_rows: int = 0
    latest_date: Optional[str] = None
    db_path: str = ""
    error: Optional[str] = None


@dataclass(frozen=True)
class PipelineStatusSnapshot:
    """Snapshot of the overall pipeline status."""
    databases: List[DatabaseStatus]


# ═══════════════════════════════════════════════════════════════════════════
# Attribution DTOs (migrated from attribution/dto.py)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FillDTO:
    """A single fill row joined with route_registry ticker/side context."""
    order_id: str
    route_id: str
    fill_id: str
    order_as_of_date: str
    mkt_timestamp: str
    broker: str
    algo: str
    fill_price: float
    fill_shares: float
    route_shares: float
    exchange: str
    equ_ticker: str
    side: str


@dataclass(frozen=True)
class ADVRecordDTO:
    """ADV record for a ticker on a given trade_date."""
    equ_ticker: str
    adv_20d: Optional[float]


@dataclass(frozen=True)
class AttributionRowDTO:
    """One row to be written to fill_attribution_metrics."""
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
    """Attribution config row from audit_attribution_config_versions."""
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
    """Audit record for a pipeline run start."""
    stage_name: str
    run_started_at: str
    status: str
    target_start_date: str
    target_end_date: str
    config_version: str
    schema_version: int


@dataclass(frozen=True)
class PipelineRunResultDTO:
    """Update to an existing pipeline run on completion."""
    run_id: int
    run_finished_at: str
    status: str
    rows_written: int
    rows_updated: int
    error_message: Optional[str]
    duration_sec: float


@dataclass(frozen=True)
class FillMetricsQueryDTO:
    """Query parameters for loading fill metrics from regime DB."""
    start_date_iso: str
    end_date_iso: str
    config_version: Optional[str] = None
    regime_dim: Optional[str] = None


@dataclass(frozen=True)
class RecommenderQueryDTO:
    """Query parameters for the algo recommender."""
    market: str
    side: int
    size_pct_adv: float
    vol_regime: Optional[str] = None
    liq_regime: Optional[str] = None
    metric: str = "is_bps"
    top_k: int = 3
    min_n: int = 30
    pct_adv_window: float = 0.5
    config_version: Optional[str] = None
    bootstrap_n: int = 5000
    rng_seed: int = 42
