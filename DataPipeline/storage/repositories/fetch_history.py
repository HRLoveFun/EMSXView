"""Fetch history repository — read/write access to fill_fetch_history.db.

Implements SqliteFetchHistoryRepository using ConnectionManager
and provides the compute_data_hash utility.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from DataPipeline.config import Config
from ._base import BaseRepository

logger = logging.getLogger(__name__)


def compute_data_hash(fills: List[Dict[str, Any]]) -> str:
    """Compute SHA-256 hash of fill data for dedup detection."""
    raw = json.dumps(fills, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SqliteFetchHistoryRepository(BaseRepository):
    """Read/write access to fill_fetch_history.db.

    Tracks fetch history for deduplication and audit.
    """

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="fill_fetch_history")

    def _ensure_schema(self, conn) -> None:
        """创建 fill_fetch_history 表（如已存在旧 schema 则自动重建）。

        检测旧表特征列 ``order_date`` 是否存在而 ``source_date`` 不存在，
        若是旧表则 DROP 后重建，旧审计记录直接舍弃。
        """
        # 检测旧 schema
        cursor = conn.execute(
            f"SELECT name FROM sqlite_master "
            f"WHERE type='table' AND name=?", (Config.FETCH_HISTORY_TABLE,)
        )
        if cursor.fetchone():
            cols = {
                row[1]
                for row in conn.execute(
                    f"PRAGMA table_info({Config.FETCH_HISTORY_TABLE})"
                ).fetchall()
            }
            # 旧表特征：有 order_date 但无 source_date
            if "order_date" in cols and "source_date" not in cols:
                logger.info(
                    "检测到 fill_fetch_history 旧 schema（列名 order_date/hash_value），"
                    "正在重建为新 schema..."
                )
                conn.execute(f"DROP TABLE {Config.FETCH_HISTORY_TABLE}")
                conn.commit()
                logger.info("fill_fetch_history 旧表已删除，将按新 schema 重建")

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.FETCH_HISTORY_TABLE} (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source_date     TEXT NOT NULL,
                data_hash       TEXT NOT NULL,
                row_count       INTEGER NOT NULL DEFAULT 0,
                file_path       TEXT,
                status          TEXT NOT NULL DEFAULT 'fetched'
                                CHECK (status IN ('fetched','deprecated','superseded','failed')),
                fetch_timestamp TEXT DEFAULT (datetime('now')),
                UNIQUE(source_date, data_hash)
            )
        """)
        conn.commit()

    def is_duplicate(self, source_date: str, data_hash: str) -> bool:
        """Check if a fetch with the given date and hash already exists."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                f"SELECT 1 FROM {Config.FETCH_HISTORY_TABLE} "
                f"WHERE source_date = ? AND data_hash = ?",
                (source_date, data_hash),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def record_fetch(
        self, source_date: str, data_hash: str, row_count: int,
        file_path: Optional[str] = None,
    ) -> int:
        """记录一次 fetch; 同 source_date 旧行软标记 'deprecated' (latest-wins)。

        与 raw_fills.db.fetch_log 的 add_fetch_log_record 保持一致语义。
        UNIQUE(source_date, data_hash) 仍保留 防止内容级重复。
        """
        conn = self._get_admin_conn()
        try:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"UPDATE {Config.FETCH_HISTORY_TABLE} SET status = 'deprecated' "
                f"WHERE source_date = ? AND status = 'fetched'",
                (source_date,),
            )
            cursor = conn.execute(
                f"INSERT OR REPLACE INTO {Config.FETCH_HISTORY_TABLE} "
                f"(source_date, data_hash, row_count, file_path, status) "
                f"VALUES (?, ?, ?, ?, 'fetched')",
                (source_date, data_hash, row_count, file_path),
            )
            conn.commit()
            logger.info(
                f"Recorded fetch for {source_date} "
                f"(hash={data_hash[:12]}..., rows={row_count})"
            )
            return cursor.lastrowid
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def get_fetch_history(
        self, source_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return fetch history records, optionally filtered by date."""
        conn = self._get_read_conn()
        try:
            if source_date:
                cursor = conn.execute(
                    f"SELECT * FROM {Config.FETCH_HISTORY_TABLE} "
                    f"WHERE source_date = ? ORDER BY fetch_timestamp DESC",
                    (source_date,),
                )
            else:
                cursor = conn.execute(
                    f"SELECT * FROM {Config.FETCH_HISTORY_TABLE} "
                    f"ORDER BY fetch_timestamp DESC"
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def add_fetch_record(
        self, order_date: str, fetch_time: str, row_count: int,
        hash_value: str, file_path: Optional[str] = None,
    ) -> None:
        """Legacy-compatible wrapper for record_fetch."""
        self.record_fetch(
            source_date=order_date.replace("-", ""),
            data_hash=hash_value,
            row_count=row_count,
            file_path=file_path,
        )

    def get_latest_fetch(self, source_date: str) -> Optional[Dict[str, Any]]:
        """Return the most recent fetch record for a source date."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                f"SELECT * FROM {Config.FETCH_HISTORY_TABLE} "
                f"WHERE source_date = ? ORDER BY fetch_timestamp DESC LIMIT 1",
                (source_date,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        finally:
            conn.close()
