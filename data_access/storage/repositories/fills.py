"""Fill repository — read-only access to processed_fills.db.

Implements SqliteFillReadRepository using ConnectionManager.
写入路径（SqliteFillWriteRepository）已随 010-extract-pipeline 迁往
独立仓库 EMSXDataPipeline（唯一写入方）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from data_access.config import Config
from ._base import BaseRepository

logger = logging.getLogger(__name__)

# 分区映射: 表名 → (目标DB键, 保留别名)
# Phase B: activated by PARTITION_DUAL_WRITE / PARTITION_READ_NEW flags
_PARTITION_DB_MAP: dict[str, str] = {
    "route_registry": "execution_history",
    "order_history": "execution_history",
    "route_history": "execution_history",
    "route_event_history": "execution_history",
    "ticker_repository": "ticker_registry",
    "equ_ticker_registry": "ticker_registry",
    "ccy_ticker_registry": "ticker_registry",
    "ticker_date_mapping": "ticker_registry",
    "order_label": "ticker_registry",
}


def _partition_db_for(table: str) -> str:
    return _PARTITION_DB_MAP.get(table, "")


class SqliteFillReadRepository(BaseRepository):
    """Read access to processed fills, route registry, and aggregations."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="processed_fills")

    def _legacy_table_is_live(self, table: str) -> bool:
        """判断 legacy 表是否仍可作为读取来源（存在且至少有一行）。

        M3.1 空壳防护：分区迁移可能在 processed_fills.db 残留 0 行空壳表
        （2026-08-26 事故：空壳 ticker_repository 导致 get_ticker_exchange_map
        返回 {}，S5 BDIB 静默短路）。仅以「表存在」为判据会把读取路由到
        空壳表；此处要求存在且非空才视为 live。EXISTS 查询命中首行即返回，
        对大表无额外开销。
        """
        try:
            conn = self._get_read_conn()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone() is not None
                if not exists:
                    return False
                has_rows = conn.execute(
                    f"SELECT EXISTS(SELECT 1 FROM [{table}])"
                ).fetchone()[0]
                return bool(has_rows)
            finally:
                conn.close()
        except Exception as exc:
            # 检测失败时保守视为 live（维持旧行为，走 legacy 路径）
            logger.debug("legacy 表状态检测失败 %s: %s", table, exc)
            return True

    def _conn_for(self, table: str):
        """B3: 根据表名路由到正确的DB (PARTITION_READ_NEW 或自动检测已迁移表)."""
        if Config.PARTITION_READ_NEW:
            target_db = _partition_db_for(table)
            if target_db:
                from data_access.storage.connection import AccessTier
                return self._mgr.get_connection(target_db, AccessTier.READ)

        # B4 后自动检测: legacy 表不存在或为 0 行空壳（M3.1）时回退到分区 DB
        target_db = _partition_db_for(table)
        if target_db and not self._legacy_table_is_live(table):
            from data_access.storage.connection import AccessTier
            return self._mgr.get_connection(target_db, AccessTier.READ)

        return self._get_read_conn()

    def get_ticker_exchange_map(
        self, exchanges: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Return {equ_ticker: exchange} from ticker_repository."""
        conn = self._conn_for("ticker_repository")
        try:
            params: List[str] = []
            where_clauses: List[str] = []
            if exchanges:
                clean = [str(e).strip().upper() for e in exchanges if str(e).strip()]
                if not clean:
                    return {}
                where_clauses.append(
                    f"UPPER(exchange) IN ({','.join(['?'] * len(clean))})"
                )
                params.extend(clean)
            query = "SELECT equ_ticker, exchange FROM ticker_repository"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            rows = conn.execute(query, params).fetchall()
            return {
                str(t): str(e).upper()
                for t, e in rows
                if t is not None and e is not None and str(e).strip()
            }
        finally:
            conn.close()

    def get_order_labels(self) -> pd.DataFrame:
        """Return order labels."""
        conn = self._conn_for("order_label")
        try:
            return pd.read_sql_query(
                "SELECT * FROM order_label", conn.raw_connection,
            )
        finally:
            conn.close()

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        """Get order labels for a specific date."""
        conn = self._conn_for("order_label")
        try:
            return pd.read_sql_query(
                "SELECT * FROM order_label WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all tables in processed_fills.db."""
        conn = self._get_read_conn()
        try:
            stats: Dict[str, Any] = {}
            for table in [
                Config.PROCESSED_FILLS_TABLE,
                Config.AGG_10S_TABLE,
                Config.AGG_1MIN_TABLE,
                Config.ORDER_HISTORY_TABLE,
                Config.ROUTE_HISTORY_TABLE,
                Config.ROUTE_EVENT_HISTORY_TABLE,
                Config.AGG_PROCESSED_FILLS_TABLE,
                Config.PROCESSED_FILLS_1MIN_TABLE,
                Config.ORDER_LABEL_TABLE,
            ]:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except Exception:
                    stats[table] = 0

            try:
                cursor = conn.execute(
                    f"SELECT stage, COUNT(DISTINCT order_as_of_date) "
                    f"FROM {Config.PROCESSING_LOG_TABLE} GROUP BY stage"
                )
                stats["processing_stages"] = {r[0]: r[1] for r in cursor.fetchall()}
            except Exception:
                stats["processing_stages"] = {}

            return stats
        finally:
            conn.close()
