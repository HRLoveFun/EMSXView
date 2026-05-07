"""
Backward-compatible facade for ``ProcessedFillsDB``.

This module provides the original ``ProcessedFillsDB`` class preserved as a
**facade** that delegates every method to the appropriate domain repository.
All existing call-sites continue to work without modification::

    from processed_fills_db import ProcessedFillsDB
    db = ProcessedFillsDB()
    db.upsert_processed_fills(df)       # delegates to ProcessedFillsRepository
    db.mark_date_processed("20260501")  # delegates to ProcessingLogRepository

New code should prefer importing specific repositories directly::

    from processed_fills_db.fills_repository import ProcessedFillsRepository
    from processed_fills_db.processing_log_repository import ProcessingLogRepository
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.src.storage.connection import AccessTier
from ._base import BaseProcessedFillsRepo, init_processed_fills_schema
from .aggregation_repository import AggregationRepository
from .fills_repository import ProcessedFillsRepository
from .execution_history_repository import ExecutionHistoryRepository
from .legacy_repository import LegacyRepository
from .order_label_repository import OrderLabelRepository
from .processing_log_repository import ProcessingLogRepository
from .stats import get_processing_stats
from .ticker_repository import TickerRepository


class ProcessedFillsDB:
    """Facade delegating to domain-specific repositories.

    Preserves the existing public API 100%.  All calls are forwarded
    to the appropriate sub-repository.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
    ):
        # Create all sub-repositories — they share the same db_path
        self._fills = ProcessedFillsRepository(db_path, access_tier)
        self._agg = AggregationRepository(db_path, access_tier)
        self._exec_hist = ExecutionHistoryRepository(db_path, access_tier)
        self._labels = OrderLabelRepository(db_path, access_tier)
        self._log = ProcessingLogRepository(db_path, access_tier)
        self._ticker = TickerRepository(db_path, access_tier)
        self._legacy = LegacyRepository(db_path, access_tier)

        # Schema init (once, coordinated) — any repo instance works
        init_processed_fills_schema(self._fills)

    # ── Expose db_path for backward compat ─────────────────────────────

    @property
    def db_path(self):
        """Path to the processed_fills.db file."""
        return self._fills.db_path

    # ── Connection access (backward compat) ───────────────────────────

    def _get_conn(self):
        """Return an access-controlled SQLite connection.

        Delegates to the fills repository for backward compatibility.
        """
        return self._fills._get_conn()

    def _get_admin_conn(self):
        """Return a raw admin connection for transaction use.

        Delegates to the fills repository for backward compatibility.
        """
        return self._fills._get_admin_conn()

    # ── Core Fills (→ ProcessedFillsRepository) ─────────────────────────

    def upsert_processed_fills(self, df: pd.DataFrame, conn=None) -> int:
        return self._fills.upsert_processed_fills(df, conn)

    def upsert_route_registry(self, df: pd.DataFrame, conn=None) -> int:
        return self._fills.upsert_route_registry(df, conn)

    def get_processed_fills_for_date(self, date_str: str, use_legacy_view: bool = False) -> pd.DataFrame:
        return self._fills.get_processed_fills_for_date(date_str, use_legacy_view)

    def get_processed_fills_for_date_range(self, start: str, end: str, use_legacy_view: bool = False) -> pd.DataFrame:
        return self._fills.get_processed_fills_for_date_range(start, end, use_legacy_view)

    def get_all_processed_fills(self, use_legacy_view: bool = False) -> pd.DataFrame:
        return self._fills.get_all_processed_fills(use_legacy_view)

    # ── Aggregation (→ AggregationRepository) ──────────────────────────

    def upsert_agg_fills_10s(self, df: pd.DataFrame, conn=None) -> int:
        count = self._agg.upsert_agg_fills_10s(df, conn)
        # Side-effect preserved from original ProcessedFillsDB:
        # aggregation write also updates ticker→exchange mapping
        self._ticker.update_ticker_repository(df, conn=conn)
        return count

    def upsert_agg_fills_1min(self, df: pd.DataFrame) -> int:
        return self._agg.upsert_agg_fills_1min(df)

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        return self._agg.get_agg_fills_10s_for_date(date_str)

    def get_agg_fills_1min_for_date(self, date_str: str) -> pd.DataFrame:
        return self._agg.get_agg_fills_1min_for_date(date_str)

    # ── Execution History (→ ExecutionHistoryRepository) ──────────────

    def upsert_order_history(self, df: pd.DataFrame, conn=None) -> int:
        return self._exec_hist.upsert_order_history(df, conn)

    def upsert_route_history(self, df: pd.DataFrame, conn=None) -> int:
        return self._exec_hist.upsert_route_history(df, conn)

    def upsert_route_event_history(self, df: pd.DataFrame, conn=None) -> int:
        return self._exec_hist.upsert_route_event_history(df, conn)

    def get_execution_history_stats(self) -> Dict[str, Any]:
        return self._exec_hist.get_execution_history_stats()

    # ── Order Labels (→ OrderLabelRepository) ──────────────────────────

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        return self._labels.upsert_order_labels(df)

    def get_order_labels(self) -> pd.DataFrame:
        return self._labels.get_order_labels()

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        return self._labels.get_order_labels_for_date(date_str)

    # ── Processing Log (→ ProcessingLogRepository) ─────────────────────

    def mark_date_processed(self, date_str: str, stage: str = "processed", row_count: int = 0, conn=None) -> None:
        return self._log.mark_date_processed(date_str, stage, row_count, conn)

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        return self._log.get_processed_dates(stage)

    def get_unprocessed_dates(self, raw_dates: List[str], stage: str = "processed") -> List[str]:
        return self._log.get_unprocessed_dates(raw_dates, stage)

    # ── Ticker Metadata (→ TickerRepository) ──────────────────────────

    def update_ticker_date_mapping(self, df: pd.DataFrame, conn=None) -> None:
        return self._ticker.update_ticker_date_mapping(df, conn)

    def get_ticker_dates(self, ticker_type: str = "equ_ticker") -> Dict[str, List[str]]:
        return self._ticker.get_ticker_dates(ticker_type)

    def update_ticker_repository(self, df: pd.DataFrame, conn=None) -> None:
        return self._ticker.update_ticker_repository(df, conn)

    def get_ticker_exchange_map(self, tickers=None, exchanges=None) -> Dict[str, str]:
        return self._ticker.get_ticker_exchange_map(tickers, exchanges)

    def update_ticker_registries(self, df: pd.DataFrame, conn=None) -> None:
        return self._ticker.update_ticker_registries(df, conn)

    def get_equ_ticker_registry(self) -> pd.DataFrame:
        return self._ticker.get_equ_ticker_registry()

    def get_ccy_ticker_registry(self) -> pd.DataFrame:
        return self._ticker.get_ccy_ticker_registry()

    # ── Legacy (→ LegacyRepository) ────────────────────────────────────

    def _upsert_df_to_table(self, df: pd.DataFrame, table_name: str, key_columns: List[str], allowed_columns=None) -> int:
        return self._legacy._upsert_df_to_table(df, table_name, key_columns, allowed_columns)

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        return self._legacy.upsert_agg_fills(df)

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        return self._legacy.get_agg_fills_for_date(date_str)

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        return self._legacy.upsert_1min_fills(df)

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        return self._legacy.get_1min_fills_for_date(date_str)

    # ── Stats (cross-domain) ───────────────────────────────────────────

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all tables."""
        return get_processing_stats(self._fills)