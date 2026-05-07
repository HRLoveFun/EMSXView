"""Repository protocols for the attribution module.

These define the data-access contracts that business logic depends on.
Concrete implementations live in repositories.py.

Using typing.Protocol (structural subtyping) means concrete repositories
do NOT need to explicitly inherit from these protocols — they just need
to implement the same method signatures. This keeps the migration path
simple and avoids forcing changes on existing code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Tuple, runtime_checkable

import pandas as pd

from .dto import (
    ADVRecordDTO,
    AttributionConfigDTO,
    AttributionRowDTO,
    FillDTO,
    FillMetricsQueryDTO,
    PipelineRunDTO,
    PipelineRunResultDTO,
    RecommenderQueryDTO,
)


# ---------------------------------------------------------------------------
# BarPanel — kept in benchmarks.py for now; re-exported here for convenience
# (will be moved to dto.py in a future iteration if we fully DTO-ify)
# ---------------------------------------------------------------------------
from .benchmarks import BarPanel  # noqa: F401 — re-export for Protocol use


# ---------------------------------------------------------------------------
# FillRepository — reads from processed_fills.db
# ---------------------------------------------------------------------------

@runtime_checkable
class FillRepository(Protocol):
    """Read access to processed fills + route registry."""

    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame:
        """Return fills with ticker/side for a given trading date.

        Columns: OrderId, RouteId, FillId, order_as_of_date, mkt_timestamp,
                 Broker, algo, FillPrice, FillShares, RouteShares, Exchange,
                 equ_ticker, Side
        """
        ...

    def get_distinct_dates_in_range(
        self, start_yyyymmdd: str, end_yyyymmdd: str,
    ) -> List[str]:
        """Return sorted list of distinct order_as_of_date values with fills."""
        ...


# ---------------------------------------------------------------------------
# BarDataRepository — reads from raw_bdib.db
# ---------------------------------------------------------------------------

@runtime_checkable
class BarDataRepository(Protocol):
    """Read access to intraday bar data (raw_bdib) and ADV (bdib_daily_summary)."""

    def get_bar_panels_for_date(
        self, yyyymmdd: str, tickers: Iterable[str],
    ) -> Dict[str, BarPanel]:
        """Return {equ_ticker: BarPanel} for date + requested tickers.

        Tickers absent from raw_bdib are simply omitted (caller marks
        data_quality_flags).
        """
        ...

    def get_adv_map(
        self, yyyymmdd: str, tickers: Iterable[str],
    ) -> Dict[str, float]:
        """Return {equ_ticker: adv_20d} from bdib_daily_summary.

        Only includes tickers with adv_20d > 0.
        """
        ...


# ---------------------------------------------------------------------------
# RegimeRepository — read+write to regime.db
# ---------------------------------------------------------------------------

@runtime_checkable
class RegimeRepository(Protocol):
    """Read+write access to regime DB (attribution metrics + regime labels + audit)."""

    def upsert_attribution_metrics(
        self, rows: List[AttributionRowDTO], *,
        batch_size: int = 5000,
    ) -> int:
        """Bulk upsert attribution metric rows. Returns total rows written."""
        ...

    def get_fill_metrics(self, query: FillMetricsQueryDTO) -> pd.DataFrame:
        """Load fill_attribution_metrics, optionally joined with regime labels.

        Returns DataFrame with standard metric columns.
        """
        ...

    def get_regime_labels(
        self, start_date_iso: str, end_date_iso: str,
        regime_dim: str, *,
        regime_config_version: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get regime labels for a date range and dimension.

        Returns DataFrame with OrderId, RouteId, FillId,
        order_as_of_date_iso, and the regime value column.
        """
        ...

    def insert_pipeline_run(self, run: PipelineRunDTO) -> int:
        """Insert an audit_pipeline_runs row. Returns run_id."""
        ...

    def update_pipeline_run(self, result: PipelineRunResultDTO) -> None:
        """Update an existing pipeline run with completion info."""
        ...

    def write_research_snapshot(
        self, run_id: int, config_version: str,
        start_date_iso: str, end_date_iso: str,
        rows_written: int, rows_total: int,
        snapshot_sha256: str, created_at: str,
    ) -> None:
        """Write a research snapshot record."""
        ...

    def compute_snapshot_hash(
        self, config_version: str, start_iso: str, end_iso: str,
    ) -> Tuple[str, int]:
        """Return (sha256_hex, total_rows_in_range) for deterministic sampling."""
        ...


# ---------------------------------------------------------------------------
# AttributionConfigRepository — config from regime.db
# ---------------------------------------------------------------------------

@runtime_checkable
class AttributionConfigRepository(Protocol):
    """Read+write access to audit_attribution_config_versions."""

    def get_active_config(self) -> Optional[AttributionConfigDTO]:
        """Return the active attribution config, or None if no config exists."""
        ...

    def seed_default_config(self) -> str:
        """Seed 'attr_v0' if none exists. Returns version_id."""
        ...

    def ensure_schema_current(self) -> None:
        """Verify regime.db schema is at the expected version."""
        ...