"""
Aggregated fills repository.

Manages the ``agg_fills_10s`` and ``agg_fills_1min`` tables — route-level
market-data aggregations used by downstream TCA calculations.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

import pandas as pd

from ..processing_config import ProcessingConfig as Config
from ..schema import AGG_1MIN_COLUMNS, AGG_COLUMNS, COLUMN_TYPE_MAP
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class AggregationRepository(BaseProcessedFillsRepo):
    """Repository for route-level 10-second and 1-minute aggregations.

    The 1-minute table is **disabled** in the pipeline since v3
    but retained for backward compatibility and ad-hoc manual use.
    """

    # ── 10-second aggregation (active) ─────────────────────────────────

    def upsert_agg_fills_10s(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace route-level 10-second aggregated fills.

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        count = self._upsert_fixed_schema(
            df,
            Config.AGG_10S_TABLE,
            key_columns=["OrderId", "RouteId", "mkt_timestamp", "order_as_of_date"],
            expected_columns=AGG_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} route-level agg fills (10s)")
        return count

    # ── 1-minute aggregation (DEPRECATED since v3) ──────────────────────

    def upsert_agg_fills_1min(self, df: pd.DataFrame) -> int:
        """[DEPRECATED v3] Insert or replace route-level 1-minute aggregated fills.

        The 1-minute aggregation has been disabled in the pipeline
        (``pipeline.py run_aggregate()``).  This method and the
        ``agg_fills_1min`` table are retained for backward compatibility
        and potential manual ad-hoc use only.
        """
        count = self._upsert_fixed_schema(
            df,
            Config.AGG_1MIN_TABLE,
            key_columns=["OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date"],
            expected_columns=AGG_1MIN_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
        )
        logger.info(f"Upserted {count} route-level agg fills (1min)")
        return count

    # ── Read operations ────────────────────────────────────────────────

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        """Get route-level 10s aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_10S_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_agg_fills_1min_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED v3] Get route-level 1min aggregated fills for a date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_1MIN_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()