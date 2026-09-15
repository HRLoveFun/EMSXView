"""Raw fill repository — read-only access to raw_fills.db.

Implements SqliteRawFillReadRepository using ConnectionManager.
写入路径（SqliteRawFillWriteRepository）已随 010-extract-pipeline 迁往
独立仓库 EMSXDataPipeline（唯一写入方）。

本仓库侧只提供**抓取日志与日期覆盖**类查询；raw_fills 行数据由
CostView 侧直接按需查询（`CostView/src/query_cli.py`）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteRawFillReadRepository(BaseRepository):
    """Read access to raw fills fetch logs and coverage."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_fills")

    def get_date_row_counts(self) -> Dict[str, int]:
        """Return row counts grouped by source_date."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT source_date, COUNT(*) FROM raw_fills "
                "WHERE source_date IS NOT NULL AND source_date != '' "
                "GROUP BY source_date ORDER BY source_date"
            )
            return {r[0]: r[1] for r in cursor.fetchall()}
        finally:
            conn.close()

    def get_fetch_log_stats(self) -> List[Dict]:
        """Return fetch_log summary."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT source_date, fetch_timestamp, row_count, "
                "data_hash, file_path, status "
                "FROM fetch_log ORDER BY fetch_timestamp DESC"
            )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_order_fetch_log(
        self,
        source_date: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Return order-level fetch log entries, optionally filtered by date."""
        conn = self._get_read_conn()
        try:
            if source_date:
                cursor = conn.execute(
                    "SELECT order_id, source_date "
                    "FROM order_fetch_log WHERE source_date = ? "
                    "ORDER BY source_date DESC LIMIT ?",
                    (source_date, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT order_id, source_date "
                    "FROM order_fetch_log "
                    "ORDER BY source_date DESC LIMIT ?",
                    (limit,),
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

