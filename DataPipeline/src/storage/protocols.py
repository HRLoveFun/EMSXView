"""Repository protocols for the CostView database subsystem.

These define the data-access contracts that business logic depends on.
Concrete implementations will live in db/repositories/ (Phase 2).

Using typing.Protocol (structural subtyping) means concrete repositories
do NOT need to explicitly inherit from these protocols — they just need
to implement the same method signatures.

Phase 1 scope: define the interfaces. Phase 2: implement them.
Phase 3: migrate all callers to use Protocol-typed references.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Tuple, runtime_checkable

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════════
# Fill domain — raw_fills.db + processed_fills.db
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class FillReadRepository(Protocol):
    """Read access to processed fills, route registry, and aggregations."""

    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame:
        """Return processed fills for a trading date."""
        ...

    def get_all_processed_fills(self) -> pd.DataFrame:
        """Return all processed fills."""
        ...

    def get_distinct_dates_in_range(
        self, start_yyyymmdd: str, end_yyyymmdd: str,
    ) -> List[str]:
        """Return sorted list of distinct order_as_of_date values with fills."""
        ...

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Return dates that have been processed for a given stage."""
        ...

    def get_unprocessed_dates(
        self, candidate_dates: List[str], stage: str = "processed",
    ) -> List[str]:
        """Return dates from candidates that have not been processed for a stage."""
        ...

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        """Return 10-second aggregated fills for a date."""
        ...

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return aggregated fills for a date (fallback)."""
        ...

    def get_ticker_exchange_map(
        self, exchanges: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Return {equ_ticker: exchange} from ticker_repository."""
        ...

    def get_order_labels(self) -> pd.DataFrame:
        """Return order labels."""
        ...


@runtime_checkable
class FillWriteRepository(Protocol):
    """Write access to processed fills, aggregations, and processing log."""

    def upsert_processed_fills(self, df: pd.DataFrame) -> int:
        """Upsert processed fills. Returns new row count."""
        ...

    def upsert_agg_fills_10s(
        self, df: pd.DataFrame, conn: object = None,
    ) -> int:
        """Upsert 10s aggregated fills. Returns row count."""
        ...

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Upsert order labels."""
        ...

    def mark_date_processed(
        self, date_str: str, stage: str, row_count: int = 0,
        conn: object = None,
    ) -> None:
        """Mark a date as processed for a given stage."""
        ...


@runtime_checkable
class FillAdminRepository(Protocol):
    """Administrative operations on fill databases."""

    def backup_database(self, database: str = "processed_fills") -> Path:
        """Create a timestamped backup."""
        ...

    def get_processing_stats(self) -> Dict[str, object]:
        """Get processing statistics across all tables."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Raw fill domain — raw_fills.db
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class RawFillReadRepository(Protocol):
    """Read access to raw fills and fetch logs."""

    def get_fills_for_source_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for a source_date."""
        ...

    def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for an order_as_of_date."""
        ...

    def get_all_source_dates(self) -> List[str]:
        """Return all distinct source_date values."""
        ...

    def get_row_count(self) -> int:
        """Return total rows in raw_fills."""
        ...


@runtime_checkable
class RawFillWriteRepository(Protocol):
    """Write access to raw fills and fetch logs."""

    def upsert_raw_api_data(
        self, fills: List[Dict], source_date: str,
    ) -> int:
        """Insert Bloomberg API raw data. Returns rows upserted."""
        ...

    def upsert_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace cleaned fill records."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Market data domain — raw_bdib.db + processed_raw_bdib.db
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class MarketDataReadRepository(Protocol):
    """Read access to BDIB bars and daily summaries."""

    def get_bdib_bars_for_date(
        self, equ_ticker: str, trade_date: str,
    ) -> pd.DataFrame:
        """Return 10s bars for a ticker+date."""
        ...

    def get_bdib_bars_for_tickers_and_dates(
        self, equ_tickers: List[str], start_date: str, end_date: str,
    ) -> pd.DataFrame:
        """Return bars for multiple tickers over a date range."""
        ...

    def get_latest_order_as_of_date(self) -> Optional[str]:
        """Return latest date in raw_bdib."""
        ...

    def get_daily_summary(
        self, equ_ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return bdib_daily_summary rows for a ticker."""
        ...

    def get_latest_daily_summary(
        self, limit: int = 25, trade_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return latest daily-summary rows."""
        ...

    def get_distinct_dates(self) -> List[str]:
        """Return distinct order_as_of_date values."""
        ...


@runtime_checkable
class MarketDataWriteRepository(Protocol):
    """Write access to BDIB bars and daily summaries."""

    def upsert_bdib_data(
        self, df: pd.DataFrame, date_str: Optional[str] = None,
    ) -> int:
        """Upsert raw BDIB bars. Returns row count."""
        ...

    def upsert_processed_bdib(self, df: pd.DataFrame) -> int:
        """Upsert processed/enhanced BDIB bars. Returns row count."""
        ...

    def upsert_daily_summary(self, rows: List[Dict]) -> int:
        """Upsert daily metrics. Returns row count."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Integrated domain — fill_bdib.db
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class IntegratedReadRepository(Protocol):
    """Read access to fill+BDIB integrated data."""

    def get_integrated_data_for_date(
        self, date_str: str,
    ) -> pd.DataFrame:
        """Return integrated fills+BDIB rows for a date."""
        ...


@runtime_checkable
class IntegratedWriteRepository(Protocol):
    """Write access to fill+BDIB integrated data."""

    def upsert_integrated_data(
        self, df: pd.DataFrame, date_str: Optional[str] = None,
    ) -> int:
        """Upsert integrated fill+BDIB data. Returns row count."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Regime domain — regime.db
# ═══════════════════════════════════════════════════════════════════════════

@runtime_checkable
class RegimeReadRepository(Protocol):
    """Read access to regime labels, distributions, and config."""

    def get_regime_distribution(
        self,
        start_date: str,
        end_date: str,
        regime_dim: str = "vol_regime",
        config_version: Optional[str] = None,
    ) -> List[Tuple[str, str, str, int]]:
        """Return (date, market_code, regime_label, count) tuples."""
        ...

    def get_active_config_version(self) -> Optional[str]:
        """Return the active regime config version."""
        ...

    def get_regime_labels(
        self, start_date_iso: str, end_date_iso: str,
        regime_dim: str, *,
        regime_config_version: Optional[str] = None,
    ) -> pd.DataFrame:
        """Get regime labels for a date range and dimension."""
        ...


@runtime_checkable
class RegimeWriteRepository(Protocol):
    """Write access to regime labels and audit tables."""

    def upsert_regime_labels(self, df: pd.DataFrame) -> int:
        """Upsert regime label rows. Returns row count."""
        ...

    def insert_pipeline_run(self, run: object) -> int:
        """Insert an audit_pipeline_runs row. Returns run_id."""
        ...


# ═══════════════════════════════════════════════════════════════════════════
# Query builder — escape hatch for complex analytical queries
# ═══════════════════════════════════════════════════════════════════════════

class FillQueryBuilder:
    """Composable query builder for fill data.

    Allows complex analytical queries while keeping SQL encapsulated
    within the repository layer. Used by tca_query_service and similar
    complex query logic.

    This is a placeholder interface — concrete implementation in Phase 2.
    """

    def for_date_range(self, start: str, end: str) -> "FillQueryBuilder":
        ...

    def with_ticker(self, ticker: str) -> "FillQueryBuilder":
        ...

    def with_side(self, side: str) -> "FillQueryBuilder":
        ...

    def with_broker(self, broker: str) -> "FillQueryBuilder":
        ...

    def execute(self) -> pd.DataFrame:
        ...
