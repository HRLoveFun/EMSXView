"""Fill repository — read/write access to processed_fills.db.

Implements SqliteFillReadRepository and SqliteFillWriteRepository
using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.schema.columns import (
    COLUMN_TYPE_MAP, PROCESSED_COLUMNS, ROUTE_REGISTRY_COLUMNS, AGG_COLUMNS,
    AGG_1MIN_COLUMNS, ORDER_HISTORY_COLUMNS, ROUTE_HISTORY_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
)
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

    def _conn_for(self, table: str):
        """B3: 根据表名路由到正确的DB (PARTITION_READ_NEW 或自动检测已迁移表)."""
        if Config.PARTITION_READ_NEW:
            target_db = _partition_db_for(table)
            if target_db:
                from DataPipeline.storage.connection import AccessTier
                return self._mgr.get_connection(target_db, AccessTier.READ)

        # B4 后自动检测: 如果原 processed_fills.db 中已无该分区表，回退到分区 DB
        target_db = _partition_db_for(table)
        if target_db:
            try:
                conn = self._get_read_conn()
                cursor = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                exists = cursor.fetchone() is not None
                conn.close()
                if not exists:
                    from DataPipeline.storage.connection import AccessTier
                    return self._mgr.get_connection(target_db, AccessTier.READ)
            except Exception:
                pass

        return self._get_read_conn()

    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame:
        """Return processed fills for a trading date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[yyyymmdd],
            )
        finally:
            conn.close()

    def get_all_processed_fills(self) -> pd.DataFrame:
        """Return all processed fills."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills", conn.raw_connection,
            )
        finally:
            conn.close()

    def get_distinct_dates_in_range(
        self, start_yyyymmdd: str, end_yyyymmdd: str,
    ) -> List[str]:
        """Return sorted list of distinct order_as_of_date values with fills."""
        conn = self._get_read_conn()
        try:
            df = pd.read_sql_query(
                "SELECT DISTINCT order_as_of_date FROM processed_fills "
                "WHERE order_as_of_date BETWEEN ? AND ? "
                "  AND ExecType='FILL' AND FillShares>0 AND FillPrice>0 "
                "ORDER BY order_as_of_date",
                conn.raw_connection,
                params=(start_yyyymmdd, end_yyyymmdd),
            )
            return df["order_as_of_date"].tolist()
        finally:
            conn.close()

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Return dates that have been processed for a given stage."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM processing_log "
                "WHERE stage = ? ORDER BY order_as_of_date",
                (stage,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_distinct_fill_dates(self) -> List[str]:
        """返回 processed_fills 表中所有不重复的 order_as_of_date 值。

        直接查询数据表而非 processing_log，避免 source_date/order_as_of_date 语义差异。
        """
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM processed_fills "
                "WHERE order_as_of_date IS NOT NULL AND order_as_of_date != '' "
                "ORDER BY order_as_of_date"
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_distinct_tickers_for_date(self, trade_date: str) -> List[str]:
        """返回某交易日 processed_fills 中所有不重复的 equ_ticker。

        003-tca-core-benchmarks: ticker_date_mapping 可能滞后于 processed_fills
        时，S7 daily metrics 用此方法回退获取当日成交 ticker。
        """
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT equ_ticker FROM processed_fills "
                "WHERE order_as_of_date = ? AND equ_ticker IS NOT NULL "
                "AND equ_ticker != ''",
                (trade_date,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_unprocessed_dates(
        self, candidate_dates: List[str], stage: str = "processed",
    ) -> List[str]:
        """Return dates from candidates that have not been processed for a stage."""
        processed = set(self.get_processed_dates(stage))
        return [d for d in candidate_dates if d not in processed]

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        """Return 10-second aggregated fills for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_10s WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return aggregated fills for a date (fallback to 1min)."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_1min WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

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

    def get_equ_ticker_registry(self) -> pd.DataFrame:
        """Get all equity tickers from the registry."""
        conn = self._conn_for("equ_ticker_registry")
        try:
            return pd.read_sql_query(
                "SELECT * FROM equ_ticker_registry ORDER BY equ_ticker",
                conn.raw_connection,
            )
        finally:
            conn.close()

    def get_ccy_ticker_registry(self) -> pd.DataFrame:
        """Get all currency tickers from the registry."""
        conn = self._conn_for("ccy_ticker_registry")
        try:
            return pd.read_sql_query(
                "SELECT * FROM ccy_ticker_registry ORDER BY ccy_ticker",
                conn.raw_connection,
            )
        finally:
            conn.close()

    def get_ticker_dates(
        self, ticker_type: str = "equ_ticker",
    ) -> Dict[str, List[str]]:
        """Get ticker→dates mapping from ticker_date_mapping table."""
        conn = self._conn_for("ticker_date_mapping")
        try:
            cur = conn.execute(
                "SELECT ticker, order_as_of_date FROM ticker_date_mapping "
                "WHERE ticker_type = ? ORDER BY ticker, order_as_of_date",
                (ticker_type,),
            )
            result: Dict[str, List[str]] = {}
            for ticker, date_str in cur.fetchall():
                result.setdefault(ticker, []).append(date_str)
            return result
        finally:
            conn.close()

    def get_processed_fills_for_date_range(
        self, start: str, end: str,
    ) -> pd.DataFrame:
        """Get processed fills for a date range (inclusive, YYYYMMDD)."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                """SELECT * FROM processed_fills
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, mkt_timestamp""",
                conn.raw_connection,
                params=[start, end],
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

    def get_execution_history_stats(self) -> Dict[str, Any]:
        """Return row counts and source policy metadata for execution history tables."""
        conn = self._conn_for("order_history")
        try:
            return {
                "order_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM order_history"
                ).fetchone()[0],
                "route_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM route_history"
                ).fetchone()[0],
                "route_event_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM route_event_history"
                ).fetchone()[0],
                "source_policy": dict(Config.EXECUTION_HISTORY_SOURCE_POLICY),
                "refresh_policy": dict(Config.EXECUTION_HISTORY_REFRESH_POLICY),
            }
        finally:
            conn.close()

    def get_agg_fills_1min_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED v3] Get route-level 1min aggregated fills for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_1min WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED] Legacy: get 1min aggregated fills for a date from old table."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills_1min WHERE order_as_of_date = ?",
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


class SqliteFillWriteRepository(BaseRepository):
    """Write access to processed fills, aggregations, and processing log."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="processed_fills")

    def _partition_dual_write(self, table: str, sql: str, rows: list) -> None:
        """双写分区DB (Phase B2: PARTITION_DUAL_WRITE)."""
        if not Config.PARTITION_DUAL_WRITE:
            return
        target_db = _partition_db_for(table)
        if not target_db:
            return
        try:
            conn = self._mgr.get_connection(target_db)
            conn.executemany(sql, rows)
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug("分区双写跳过 %s: %s", table, e)

    def _upsert_to_partition(
        self, df, table: str, expected_columns: list, target_db: str,
    ) -> None:
        """写入分区DB."""
        conn = self._mgr.get_connection(target_db)
        try:
            self._upsert_fixed_schema(
                df, table, key_columns=[], expected_columns=expected_columns,
                type_map=COLUMN_TYPE_MAP, conn=conn,
            )
            conn.commit()
        finally:
            conn.close()

    def _get_connection_for_table(self, table: str):
        """B3: 读取时路由到分区DB."""
        if Config.PARTITION_READ_NEW:
            target_db = _partition_db_for(table)
            if target_db:
                return self._mgr.get_connection(target_db, AccessTier.READ)
        return self._get_read_conn()

    def _upsert(
        self, df: pd.DataFrame, table: str,
        key_columns: List[str], expected_columns: List[str],
        conn: Optional[object] = None,
    ) -> int:
        """Upsert DataFrame rows into a fixed-schema table.

        B4迁移后: 分区表（route_registry等）已迁至独立DB，
        写入时自动路由到正确分区DB；非分区表仍写入 processed_fills.db。
        如有 conn 则调用者控制事务, 否则自动提交。
        """
        if df.empty:
            return 0
        own_conn = conn is None
        if own_conn:
            # B4: 分区表路由到目标DB，非分区表保持原路径
            target_db = _partition_db_for(table)
            if target_db:
                conn = self._mgr.get_connection(target_db)
            else:
                conn = self._get_write_conn()
        try:
            count = self._upsert_fixed_schema(
                df, table, key_columns=key_columns,
                expected_columns=expected_columns,
                type_map=COLUMN_TYPE_MAP, conn=conn,
            )
            if own_conn:
                conn.commit()
            return count
        finally:
            if own_conn:
                conn.close()

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Upsert order labels (dynamic-column upsert).

        B4迁移后 order_label 已迁至 ticker_registry.db，写入时直接
        路由到正确分区DB，避免在旧 processed_fills.db 中误建表。

        自动检测并补全缺失列：如果 DataFrame 包含表中不存在的列，
        先执行 ALTER TABLE ADD COLUMN 再插入数据。
        """
        if df.empty:
            return 0

        # B4后: order_label 已在 ticker_registry.db，写入分区DB
        target_db = _partition_db_for("order_label")
        if target_db:
            conn = self._mgr.get_connection(target_db)
        else:
            conn = self._get_write_conn()

        try:
            # 检测表已有列，为缺失列自动执行 ALTER TABLE ADD COLUMN
            # M9: 改用 execute_ddl 显式越权通道 (替代 raw_connection 绕过访问控制)
            raw_conn = conn.raw_connection
            existing_cols = {
                row[1] for row in raw_conn.execute("PRAGMA table_info(order_label)").fetchall()
            }
            cols = list(df.columns)
            for col in cols:
                if col not in existing_cols:
                    logger.info("order_label 表缺少列 %s，通过 execute_ddl 自动添加", col)
                    self._mgr.execute_ddl(
                        target_db or "processed_fills",
                        f'ALTER TABLE order_label ADD COLUMN "{col}" TEXT',
                    )

            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(f'"{c}"' for c in cols)
            sql = f"INSERT OR REPLACE INTO order_label ({col_names}) VALUES ({placeholders})"
            rows = [tuple(r) for r in df[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def mark_date_processed(
        self, date_str: str, stage: str, row_count: int = 0,
        conn: Optional[object] = None,
    ) -> None:
        """Mark a date as processed for a given stage."""
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.execute(
                f"INSERT OR REPLACE INTO {Config.PROCESSING_LOG_TABLE} "
                f"(order_as_of_date, row_count, stage) VALUES (?, ?, ?)",
                (date_str, row_count, stage),
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    @staticmethod
    def _upsert_fixed_schema(
        df: pd.DataFrame, table: str, *,
        key_columns: list, expected_columns: list,
        type_map: dict, conn,
    ) -> int:
        """Upsert DataFrame into a fixed-schema table."""
        insert_columns = [c for c in expected_columns if c in df.columns]
        if not insert_columns:
            return 0
        placeholders = ", ".join(["?"] * len(insert_columns))
        col_names = ", ".join(insert_columns)
        sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"

        rows = []
        for tup in df[insert_columns].itertuples(index=False, name=None):
            values = []
            for i, col in enumerate(insert_columns):
                val = tup[i]
                if val is None or (isinstance(val, float) and val != val):
                    values.append(None)
                elif col in type_map:
                    target = type_map[col]
                    if target == "REAL":
                        values.append(float(val) if val is not None else None)
                    elif target == "INTEGER":
                        values.append(int(val) if val is not None else None)
                    else:
                        values.append(str(val) if val is not None else None)
                else:
                    values.append(str(val) if val is not None else None)
            rows.append(tuple(values))

        conn.executemany(sql, rows)
        return len(rows)

    def upsert_processed_fills(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert processed fills. Returns new row count.

        v2 修复: key_columns 改为 4 元组 `(OrderId, RouteId, FillId, order_as_of_date)`，
        与 DDL 主键 `PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)` 对齐
        （`inline_ddl.init_processed_fills_schema` line 285）。

        原 `[FillId]` 单独作 key 仅在 Bloomberg 文档语义下 `FillId` 唯一时正确；当同一 FillId
        出现在多个日期/订单/路由组合时，会与 DDL 主键冲突。`INSERT OR REPLACE` 当前实际依赖
        SQLite 唯一键判重（`_upsert_fixed_schema` 不使用 `key_columns` 生成 ON CONFLICT），变更
        不影响运行时行为；目的是与 schema 语义保持一致，避免未来 SQLite 升级时行为漂移。
        """
        return self._upsert(
            df, Config.PROCESSED_FILLS_TABLE,
            ["OrderId", "RouteId", "FillId", "order_as_of_date"],
            PROCESSED_COLUMNS, conn,
        )

    def upsert_agg_fills_10s(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Upsert 10s aggregated fills. Returns row count."""
        return self._upsert(
            df, Config.AGG_10S_TABLE,
            ["OrderId", "RouteId", "mkt_timestamp", "order_as_of_date"],
            AGG_COLUMNS, conn,
        )

    def upsert_route_registry(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route registry records."""
        return self._upsert(df, "route_registry", ["OrderId", "RouteId"], ROUTE_REGISTRY_COLUMNS, conn)

    def upsert_agg_fills_1min(self, df: pd.DataFrame) -> int:
        """[DEPRECATED v3] Insert or replace route-level 1-minute aggregated fills."""
        return self._upsert(df, Config.AGG_1MIN_TABLE,
                            ["OrderId", "RouteId", "mkt_timestamp_1min", "order_as_of_date"],
                            AGG_1MIN_COLUMNS)

    def upsert_order_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """[DEPRECATED PR-1] order_history 现在是 route_history 的 VIEW 派生。

        本方法保留仅为 API 兼容；调用方会立即触发 "Cannot modify a view"
        错误。请停止调用，本方法将在 PR-2（孤儿 API 退役）后删除。
        """
        import warnings
        warnings.warn(
            "upsert_order_history() 已废弃：order_history 是 route_history 的 VIEW 派生，"
            "请通过 upsert_route_history() 写入。",
            DeprecationWarning,
            stacklevel=2,
        )
        if df.empty:
            return 0
        # 兜底：仅对 route_history 实际写入；order_history 由 VIEW 派生
        return self._upsert(df, Config.ROUTE_HISTORY_TABLE,
                            ["OrderId", "RouteId", "order_as_of_date"], ROUTE_HISTORY_COLUMNS, conn)

    def upsert_route_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route history records."""
        return self._upsert(df, Config.ROUTE_HISTORY_TABLE,
                            ["OrderId", "RouteId", "order_as_of_date"], ROUTE_HISTORY_COLUMNS, conn)

    def upsert_route_event_history(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> int:
        """Insert or replace route event history records."""
        return self._upsert(df, Config.ROUTE_EVENT_HISTORY_TABLE,
                            ["event_id"], ROUTE_EVENT_HISTORY_COLUMNS, conn)

    def get_route_registry_for_date(self, date_str: str) -> pd.DataFrame:
        """Return route_registry rows joined with processed fills for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT DISTINCT r.* FROM route_registry r "
                "INNER JOIN processed_fills p ON r.OrderId = p.OrderId AND r.RouteId = p.RouteId "
                "WHERE p.order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def upsert_execution_history(
        self, route_df: pd.DataFrame, event_df: pd.DataFrame,
    ) -> None:
        """Upsert route/event history tables (PR-1: 不再写 order_history).

        B4迁移后这些表已迁至 execution_history.db，直接使用分区路由。
        order_history 是 route_history 的 VIEW 派生，无需单独写入。
        """
        # B4: 统一写入 execution_history.db
        target_db = _partition_db_for("route_history")
        if target_db:
            conn = self._mgr.get_connection(target_db)
        else:
            conn = self._get_write_conn()
        try:
            if not route_df.empty:
                self.upsert_route_history(route_df, conn)
            if not event_df.empty:
                self.upsert_route_event_history(event_df, conn)
            conn.commit()
        finally:
            conn.close()

    def update_ticker_date_mapping(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Update ticker→date mapping from processed fills DataFrame."""
        if df.empty:
            return
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            records = []
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("equ_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "equ_ticker", str(date_str)))
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("ccy_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "ccy_ticker", str(date_str)))
            if records:
                conn.executemany(
                    f"INSERT OR IGNORE INTO {Config.TICKER_DATE_MAPPING_TABLE} "
                    "(ticker, ticker_type, order_as_of_date) VALUES (?, ?, ?)",
                    records,
                )
                if own_conn:
                    conn.commit()
        finally:
            if own_conn:
                conn.close()

    def update_ticker_repository(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Upsert equ_ticker → Exchange mapping from aggregated fills."""
        if df.empty or "equ_ticker" not in df.columns or "Exchange" not in df.columns:
            return
        work = df[["equ_ticker", "Exchange"]].dropna().copy()
        if work.empty:
            return
        work["equ_ticker"] = work["equ_ticker"].astype(str).str.strip()
        work["Exchange"] = work["Exchange"].astype(str).str.strip().str.upper()
        work = work[
            work["equ_ticker"].ne("")
            & work["equ_ticker"].str.lower().ne("none")
            & work["equ_ticker"].str.lower().ne("nan")
            & work["Exchange"].ne("")
            & work["Exchange"].str.lower().ne("none")
            & work["Exchange"].str.lower().ne("nan")
        ]
        if work.empty:
            return
        pairs = list(
            work.drop_duplicates(subset=["equ_ticker"])[["equ_ticker", "Exchange"]].itertuples(
                index=False, name=None
            )
        )
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.executemany(
                "INSERT INTO ticker_repository (equ_ticker, exchange, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(equ_ticker) DO UPDATE SET "
                "    exchange = excluded.exchange, "
                "    updated_at = datetime('now')",
                pairs,
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def update_ticker_registries(
        self, df: pd.DataFrame, conn: Optional[object] = None,
    ) -> None:
        """Update equ_ticker_registry and ccy_ticker_registry from processed fills."""
        if df.empty:
            return
        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                equ_groups = (
                    df.groupby("equ_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )
                for _, row in equ_groups.iterrows():
                    ticker = str(row["equ_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"INSERT INTO {Config.EQU_TICKER_REGISTRY_TABLE} "
                        "(equ_ticker, first_seen_date, last_seen_date, order_count) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(equ_ticker) DO UPDATE SET "
                        "    first_seen_date = MIN(first_seen_date, excluded.first_seen_date), "
                        "    last_seen_date = MAX(last_seen_date, excluded.last_seen_date), "
                        "    order_count = order_count + excluded.order_count",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                ccy_groups = (
                    df.groupby("ccy_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )
                for _, row in ccy_groups.iterrows():
                    ticker = str(row["ccy_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"INSERT INTO {Config.CCY_TICKER_REGISTRY_TABLE} "
                        "(ccy_ticker, first_seen_date, last_seen_date, order_count) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(ccy_ticker) DO UPDATE SET "
                        "    first_seen_date = MIN(first_seen_date, excluded.first_seen_date), "
                        "    last_seen_date = MAX(last_seen_date, excluded.last_seen_date), "
                        "    order_count = order_count + excluded.order_count",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def _upsert_df_to_table(
        self, df: pd.DataFrame, table_name: str,
        key_columns: List[str],
        allowed_columns: Optional[Set] = None,
    ) -> int:
        """Legacy dynamic-schema upsert (kept for backward compatibility)."""
        if df.empty:
            return 0
        if allowed_columns is not None:
            full_allowed = allowed_columns | set(key_columns)
            unknown = set(df.columns) - full_allowed
            if unknown:
                logger.warning(
                    f"_upsert_df_to_table({table_name}): dropping {len(unknown)} "
                    f"unknown columns not in whitelist: {sorted(unknown)}"
                )
                df = df[[c for c in df.columns if c in full_allowed]]
        conn = self._get_admin_conn()
        try:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col in df.columns:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN [{col}] TEXT")
            insert_cols = list(df.columns)
            placeholders = ", ".join(["?"] * len(insert_cols))
            col_names = ", ".join(f"[{c}]" for c in insert_cols)
            sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"
            rows = []
            for _, row in df.iterrows():
                values = []
                for col in insert_cols:
                    val = row.get(col)
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))
            conn.executemany(sql, rows)
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 10s aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df, Config.AGG_PROCESSED_FILLS_TABLE,
            ["OrderId", "mkt_timestamp", "order_as_of_date"],
        )
        return count

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        """[DEPRECATED] Legacy: upsert 1min aggregated fills (dynamic schema)."""
        count = self._upsert_df_to_table(
            df, Config.PROCESSED_FILLS_1MIN_TABLE,
            ["OrderId", "mkt_timestamp_1min", "order_as_of_date"],
        )
        return count
