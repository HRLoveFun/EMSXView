"""
Processed fills and route registry repository.

Manages the core fact table (``processed_fills``) and its primary dimension
table (``route_registry``), plus the ``v_processed_fills_legacy`` compatibility
view.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Optional

import pandas as pd

from ..processing_config import ProcessingConfig as Config
from ..schema import COLUMN_TYPE_MAP, PROCESSED_COLUMNS, ROUTE_REGISTRY_COLUMNS
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class ProcessedFillsRepository(BaseProcessedFillsRepo):
    """Repository for processed fills and route registry CRUD.

    Manages the ``processed_fills`` (fact) and ``route_registry``
    (dimension) tables in ``processed_fills.db``.
    """

    # ── Processed fills (fact table) ────────────────────────────────────

    def upsert_processed_fills(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace processed fill records (Fact table).

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        count = self._upsert_fixed_schema(
            df,
            Config.PROCESSED_FILLS_TABLE,
            key_columns=["FillId"],
            expected_columns=PROCESSED_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} processed fills (Fact table schema)")
        return count

    # ── Route registry (dimension table) ───────────────────────────────

    def upsert_route_registry(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace route registry records.

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        count = self._upsert_fixed_schema(
            df,
            "route_registry",
            key_columns=["OrderId", "RouteId"],
            expected_columns=ROUTE_REGISTRY_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} route registry records")
        return count

    # ── Read operations ────────────────────────────────────────────────

    def get_processed_fills_for_date(
        self,
        date_str: str,
        use_legacy_view: bool = False,
    ) -> pd.DataFrame:
        """Get processed fills for a specific ``order_as_of_date``.

        If ``use_legacy_view`` is True, reads from
        ``v_processed_fills_legacy`` to provide the old 27-column structure.
        """
        table_or_view = (
            "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        )
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {table_or_view} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_processed_fills_for_date_range(
        self,
        start: str,
        end: str,
        use_legacy_view: bool = False,
    ) -> pd.DataFrame:
        """Get processed fills for a date range (inclusive, YYYYMMDD)."""
        table_or_view = (
            "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        )
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"""SELECT * FROM {table_or_view}
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, mkt_timestamp""",
                conn,
                params=[start, end],
            )
        finally:
            conn.close()

    def get_all_processed_fills(self, use_legacy_view: bool = False) -> pd.DataFrame:
        """Get all processed fills."""
        table_or_view = (
            "v_processed_fills_legacy" if use_legacy_view else Config.PROCESSED_FILLS_TABLE
        )
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {table_or_view}",
                conn,
            )
        finally:
            conn.close()