"""
Execution history repository.

Manages the ``order_history``, ``route_history``, and
``route_event_history`` tables — the dimensional history of EMSX
order lifecycle events.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, Optional

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.common.schema import (
    COLUMN_TYPE_MAP,
    ORDER_HISTORY_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
)
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class ExecutionHistoryRepository(BaseProcessedFillsRepo):
    """Repository for order, route, and route-event history tables."""

    # ── Order history ──────────────────────────────────────────────────

    def upsert_order_history(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace order history records."""
        count = self._upsert_fixed_schema(
            df,
            Config.ORDER_HISTORY_TABLE,
            key_columns=["OrderId", "order_as_of_date"],
            expected_columns=ORDER_HISTORY_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} order history records")
        return count

    # ── Route history ──────────────────────────────────────────────────

    def upsert_route_history(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace route history records."""
        count = self._upsert_fixed_schema(
            df,
            Config.ROUTE_HISTORY_TABLE,
            key_columns=["OrderId", "RouteId", "order_as_of_date"],
            expected_columns=ROUTE_HISTORY_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} route history records")
        return count

    # ── Route event history ────────────────────────────────────────────

    def upsert_route_event_history(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        """Insert or replace route event history records."""
        count = self._upsert_fixed_schema(
            df,
            Config.ROUTE_EVENT_HISTORY_TABLE,
            key_columns=["event_id"],
            expected_columns=ROUTE_EVENT_HISTORY_COLUMNS,
            type_map=COLUMN_TYPE_MAP,
            conn=conn,
        )
        logger.info(f"Upserted {count} route event history records")
        return count

    # ── Stats ──────────────────────────────────────────────────────────

    def get_execution_history_stats(self) -> Dict[str, Any]:
        """Return row counts and source policy metadata for execution history tables."""
        conn = self._get_conn()
        try:
            return {
                "order_history_rows": conn.execute(
                    f"SELECT COUNT(*) FROM {Config.ORDER_HISTORY_TABLE}"
                ).fetchone()[0],
                "route_history_rows": conn.execute(
                    f"SELECT COUNT(*) FROM {Config.ROUTE_HISTORY_TABLE}"
                ).fetchone()[0],
                "route_event_history_rows": conn.execute(
                    f"SELECT COUNT(*) FROM {Config.ROUTE_EVENT_HISTORY_TABLE}"
                ).fetchone()[0],
                "source_policy": dict(Config.EXECUTION_HISTORY_SOURCE_POLICY),
                "refresh_policy": dict(Config.EXECUTION_HISTORY_REFRESH_POLICY),
            }
        finally:
            conn.close()