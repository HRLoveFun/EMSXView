"""Data Transfer Objects for the attribution module.

Pure data containers with no DB knowledge. These act as the contract
between the business logic layer (writer, aggregator, recommender) and
the data access layer (repositories).

When the attribution module reads from or writes to any database,
it does so through these DTOs rather than raw SQL rows or sqlite3 objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Fill data (read from processed_fills.db)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillDTO:
    """A single fill row joined with route_registry ticker/side context.

    Produced by FillRepository.get_fills_for_date().
    """
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


# ---------------------------------------------------------------------------
# ADV data (read from raw_bdib.db / bdib_daily_summary)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ADVRecordDTO:
    """ADV record for a ticker on a given trade_date.

    Produced by BarDataRepository.get_adv_map().
    """
    equ_ticker: str
    adv_20d: Optional[float]


# ---------------------------------------------------------------------------
# Attribution output rows (written to regime.db.fill_attribution_metrics)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttributionRowDTO:
    """One row to be written to fill_attribution_metrics.

    Consumed by RegimeRepository.upsert_attribution_metrics().
    """
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


# ---------------------------------------------------------------------------
# Attribution config (read from regime.db.audit_attribution_config_versions)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AttributionConfigDTO:
    """Attribution config row from audit_attribution_config_versions.

    Produced by AttributionConfigRepository.get_active_config().
    """
    version_id: str
    bench_methods: List[str]
    reversal_windows_min: List[int]
    winsor_pct: float
    adv_window_days: int
    bootstrap_n: int
    min_cell_n: int
    description: Optional[str]


# ---------------------------------------------------------------------------
# Pipeline run audit (written to regime.db.audit_pipeline_runs)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Query parameters for reading fill metrics (aggregator)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FillMetricsQueryDTO:
    """Query parameters for loading fill metrics from regime DB."""
    start_date_iso: str
    end_date_iso: str
    config_version: Optional[str] = None
    regime_dim: Optional[str] = None


# ---------------------------------------------------------------------------
# Recommender query parameters
# ---------------------------------------------------------------------------

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