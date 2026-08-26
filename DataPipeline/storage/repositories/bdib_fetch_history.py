"""BDIB fetch history repository — read/write access to bdib_fetch_history.db.

对齐 fill_fetch_history（DataPipeline/storage/repositories/fetch_history.py）：
记录每个交易日从 Bloomberg 拉取 BDIB 行情的历史，用于审计与覆盖率排查。

与 fill_fetch_history 的差异：
- source_date 语义为"数据交易日"（raw_bdib.order_as_of_date），而非拉取执行日
- 额外记录 ticker_count（该交易日实际拉取的 ticker 数）
- data_hash 为轻量指纹（ticker 集合 + 行数），不遍历全量 bar 数据
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Iterable, List, Optional

from DataPipeline.config import Config
from ._base import BaseRepository

logger = logging.getLogger(__name__)


def compute_bdib_data_hash(tickers: Iterable[str], row_count: int) -> str:
    """计算 BDIB 拉取内容轻量指纹（SHA-256）。

    基于排序去重后的 ticker 集合与行数计算，避免对百万级 bar 数据做
    全量序列化（回填窗口可达上百个交易日）。ticker 集合 + 行数即可
    区分绝大多数内容级差异，满足审计与重复拉取检测需求。

    Args:
        tickers: 本次拉取涉及的 ticker 集合
        row_count: 本次拉取写入的 bar 行数

    Returns:
        SHA-256 十六进制摘要
    """
    ticker_part = "|".join(sorted({str(t) for t in tickers if str(t)}))
    raw = f"tickers={ticker_part};rows={int(row_count)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SqliteBdibFetchHistoryRepository(BaseRepository):
    """Read/write access to bdib_fetch_history.db.

    Tracks per-trading-day BDIB fetch history for audit and coverage review,
    mirroring the fill_fetch_history schema (latest-wins per source_date).
    """

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="bdib_fetch_history")

    def _ensure_schema(self, conn) -> None:
        """创建 bdib_fetch_history 表（幂等）。"""
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.BDIB_FETCH_HISTORY_TABLE} (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                source_date     TEXT NOT NULL,
                data_hash       TEXT NOT NULL,
                row_count       INTEGER NOT NULL DEFAULT 0,
                ticker_count    INTEGER NOT NULL DEFAULT 0,
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
                f"SELECT 1 FROM {Config.BDIB_FETCH_HISTORY_TABLE} "
                f"WHERE source_date = ? AND data_hash = ?",
                (source_date, data_hash),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def record_fetch(
        self, source_date: str, data_hash: str, row_count: int,
        ticker_count: int = 0, file_path: Optional[str] = None,
    ) -> int:
        """记录一次 BDIB 拉取；同 source_date 旧行软标记 'deprecated'（latest-wins）。

        与 fill_fetch_history.record_fetch 保持一致语义：
        - 同 source_date 的 fetched 行置为 deprecated（保留审计）
        - UNIQUE(source_date, data_hash) 防止内容级重复
        """
        conn = self._get_admin_conn()
        try:
            self._ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"UPDATE {Config.BDIB_FETCH_HISTORY_TABLE} SET status = 'deprecated' "
                f"WHERE source_date = ? AND status = 'fetched'",
                (source_date,),
            )
            cursor = conn.execute(
                f"INSERT OR REPLACE INTO {Config.BDIB_FETCH_HISTORY_TABLE} "
                f"(source_date, data_hash, row_count, ticker_count, file_path, status) "
                f"VALUES (?, ?, ?, ?, ?, 'fetched')",
                (source_date, data_hash, int(row_count), int(ticker_count), file_path),
            )
            conn.commit()
            logger.info(
                f"Recorded BDIB fetch for {source_date} "
                f"(hash={data_hash[:12]}..., rows={row_count}, tickers={ticker_count})"
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
                    f"SELECT * FROM {Config.BDIB_FETCH_HISTORY_TABLE} "
                    f"WHERE source_date = ? ORDER BY fetch_timestamp DESC, id DESC",
                    (source_date,),
                )
            else:
                cursor = conn.execute(
                    f"SELECT * FROM {Config.BDIB_FETCH_HISTORY_TABLE} "
                    f"ORDER BY fetch_timestamp DESC, id DESC"
                )
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_latest_fetch(self, source_date: str) -> Optional[Dict[str, Any]]:
        """Return the most recent fetch record for a source date."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                f"SELECT * FROM {Config.BDIB_FETCH_HISTORY_TABLE} "
                f"WHERE source_date = ? ORDER BY fetch_timestamp DESC, id DESC LIMIT 1",
                (source_date,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        finally:
            conn.close()
