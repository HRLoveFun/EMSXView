"""
Processing log repository.

Manages the ``processing_log`` table — a per-date stage tracker
recording which dates have been processed at which pipeline stage
(processed → aggregated → labeled → …).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import List, Optional

from ..processing_config import ProcessingConfig as Config
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class ProcessingLogRepository(BaseProcessedFillsRepo):
    """Repository for processing-log tracking (date-stage watermark)."""

    def mark_date_processed(
        self,
        date_str: str,
        stage: str = "processed",
        row_count: int = 0,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Record that a date has been processed at a given stage.

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.execute(
                f"""INSERT OR REPLACE INTO {Config.PROCESSING_LOG_TABLE}
                    (order_as_of_date, row_count, stage)
                    VALUES (?, ?, ?)""",
                (date_str, row_count, stage),
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Get all dates that have been processed at a given stage."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT order_as_of_date
                    FROM {Config.PROCESSING_LOG_TABLE}
                    WHERE stage = ?
                    ORDER BY order_as_of_date""",
                (stage,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_unprocessed_dates(
        self,
        raw_dates: List[str],
        stage: str = "processed",
    ) -> List[str]:
        """Get dates from ``raw_dates`` that haven't been processed at the given stage."""
        processed = set(self.get_processed_dates(stage))
        return [d for d in raw_dates if d not in processed]