"""Raw fill repository — read/write access to raw_fills.db.

Implements SqliteRawFillReadRepository and SqliteRawFillWriteRepository
using ConnectionManager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from data_access.config import Config
from data_access.storage.schema.columns import ALL_RAW_COLUMNS, EMSX_FILL_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteRawFillReadRepository(BaseRepository):
    """Read access to raw fills and fetch logs."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_fills")

    def get_fills_for_source_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for a source_date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE source_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return raw fills for an order_as_of_date. Accepts YYYYMMDD or YYYY-MM-DD.

        raw_fills stores order_as_of_date as full datetime string (e.g.
        "2025-09-15 00:00:00"), so we normalize YYYYMMDD input to ISO date and
        try multiple matching strategies for robustness."""
        conn = self._get_read_conn()
        try:
            # 1) Direct match (e.g. full datetime string or YYYY-MM-DD)
            df = pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
            if not df.empty:
                return df
            # 2) YYYYMMDD -> YYYY-MM-DD conversion
            iso = None
            if isinstance(date_str, str) and len(date_str) == 8 and date_str.isdigit():
                iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
            if iso:
                df = pd.read_sql_query(
                    "SELECT * FROM raw_fills WHERE substr(order_as_of_date, 1, 10) = ?",
                    conn.raw_connection,
                    params=[iso],
                )
                if not df.empty:
                    return df
            # 3) Fallback: match by source_date
            return pd.read_sql_query(
                "SELECT * FROM raw_fills WHERE source_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_all_source_dates(self) -> List[str]:
        """Return all distinct source_date values."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT source_date FROM raw_fills "
                "WHERE source_date IS NOT NULL AND source_date != '' "
                "ORDER BY source_date"
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_distinct_order_as_of_dates(self) -> List[str]:
        """Return all distinct order_as_of_date values in raw_fills -- the S2 incremental processing key.

        raw_fills stores order_as_of_date as full datetime string (e.g.
        "2025-09-15 00:00:00"), but downstream code (processing_log,
        S2 target_dates, etc.) uses the YYYYMMDD short form. Normalize here to keep
        a single canonical representation across the pipeline."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM raw_fills "
                "WHERE order_as_of_date IS NOT NULL AND order_as_of_date != '' "
                "ORDER BY order_as_of_date"
            )
            oads: List[str] = []
            for r in cursor.fetchall():
                v = r[0]
                if not v:
                    continue
                # Normalize to YYYYMMDD
                compact = v.replace("-", "").split(" ")[0]
                oads.append(compact)
            return oads
        finally:
            conn.close()

    def get_row_count(self) -> int:
        """Return total rows in raw_fills."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM raw_fills")
            return cursor.fetchone()[0]
        finally:
            conn.close()

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

    def get_last_fetch_date(self) -> Optional[str]:
        """Return the most recent source_date in fetch_log."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT MAX(source_date) FROM fetch_log WHERE status = 'fetched'"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()


class SqliteRawFillWriteRepository(BaseRepository):
    """Write access to raw fills and fetch logs."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_fills")

    def check_fetch_duplicate(self, source_date: str, data_hash: str) -> bool:
        """Check if a fetch with the given date and hash already exists."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM fetch_log WHERE source_date = ? AND data_hash = ?",
                (source_date, data_hash),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def upsert_raw_api_data(
        self, fills: List[Dict[str, Any]], source_date: str,
    ) -> int:
        """Insert Bloomberg API raw data directly. Returns rows upserted."""
        if not fills:
            return 0

        # Compute order_as_of_date from DateTimeOfFill via derive_exchange_times
        df = pd.DataFrame(fills)

        # ══ 修复: 恢复荷兰交易所代码 "NA" (pandas 默认将字符串 "NA" 解析为 NaN)
        # 这是数据写入 raw_fills.db 的入口，此处修复可防止 "nan" 永久化到数据库
        if "Exchange" in df.columns:
            exchange_na_mask = df["Exchange"].isna()
            if exchange_na_mask.any():
                for i in exchange_na_mask[exchange_na_mask].index:
                    original = fills[i].get("Exchange")
                    if original == "NA":
                        df.at[i, "Exchange"] = "NA"

        # ══ 修复: 恢复 Ticker 值为 BBG 字符串 "NA" (pandas 默认将字符串 "NA" 解析为 NaN)
        # 与 Exchange NaN->NA 修复同入口同模式: National Bank of Canada 的 BBG ticker
        # mnemonic 即 'NA', pandas pd.DataFrame(fills) 同样会把字符串 "NA" 误解析为 NaN,
        # 落库后变成 NULL, 下游 fill_processor.add_equity_ticker 的 blank_mask 触发置
        # equ_ticker=NaN, 导致 CostView TCA JOIN 失配. 本修复从原始 fills 字典反查真值.
        if "Ticker" in df.columns:
            ticker_na_mask = df["Ticker"].isna()
            if ticker_na_mask.any():
                for i in ticker_na_mask[ticker_na_mask].index:
                    original = fills[i].get("Ticker")
                    if original == "NA":
                        df.at[i, "Ticker"] = "NA"

        if "DateTimeOfFill" in df.columns:
            from data_access.processing.fill_cleaner import derive_exchange_times
            df = derive_exchange_times(df)
            oaod = df["order_as_of_date"].fillna("").astype(str).tolist()
        else:
            oaod = [""] * len(fills)

        conn = self._get_write_conn()
        try:
            # v2 修复 (2026-07-02): cols 补上 exchange_exec_time 派生字段
            # 原 cols = EMSX_FILL_COLUMNS + ['order_as_of_date', 'source_date', 'fetched_at']
            # 缺失 exchange_exec_time 导致 4.6M 行 (41.7%) 该字段 NULL,
            # 下游 S2 修复了源 bug 后历史数据无法回溯。详见历史调查文档
            # docs/archive/2026-07-02/raw_fills_null_investigation.md 第一节问题 1
            # (已于 2026-08-12 随归档清理删除, 见 git 历史)。
            cols = (
                list(EMSX_FILL_COLUMNS)
                + ["order_as_of_date", "exchange_exec_time",
                   "source_date", "fetched_at"]
            )
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            sql = f"INSERT OR REPLACE INTO raw_fills ({col_names}) VALUES ({placeholders})"

            now = datetime.now().isoformat()
            rows = []
            for i, f in enumerate(fills):
                row = []
                for col in EMSX_FILL_COLUMNS:
                    val = f.get(col)
                    row.append(None if val is None else str(val))
                row.append(oaod[i])
                # v2 修复: 同步写入 exchange_exec_time, 与 oaod 同源
                eet = df["exchange_exec_time"].iloc[i] if "exchange_exec_time" in df.columns else ""
                row.append("" if (eet is None or (hasattr(eet, "isna") and eet.isna())) else str(eet))
                row.append(source_date)
                row.append(now)
                rows.append(tuple(row))

            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} raw API rows (source_date={source_date})")
            return len(rows)
        finally:
            conn.close()

    def add_fetch_log_record(
        self, source_date: str, row_count: int, data_hash: str,
        file_path: Optional[str] = None,
    ) -> None:
        """记录一次 fetch 操作; 同 source_date 旧行自动软标记 'deprecated'。

        业务约定: 同一 source_date 允许多次拉取 (late fills、scope 切换、
        Bloomberg 修正等), 最新一次为 'fetched', 历史行标 'deprecated' 最新获胜。
        UNIQUE(source_date, data_hash) 仍保留 防止内容级重复。
        """
        conn = self._get_write_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 软标记同 source_date 旧 'fetched' 行为 'deprecated'
            conn.execute(
                "UPDATE fetch_log SET status = 'deprecated' "
                "WHERE source_date = ? AND status = 'fetched'",
                (source_date,),
            )
            # INSERT OR REPLACE 兜底 force 路径可能产生 (source_date, data_hash) 相同
            conn.execute(
                "INSERT OR REPLACE INTO fetch_log "
                "(source_date, row_count, data_hash, file_path, status) "
                "VALUES (?, ?, ?, ?, 'fetched')",
                (source_date, row_count, data_hash, file_path),
            )
            conn.commit()
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def record_fetch_failed(
        self, source_date: str, reason: str,
        detail: Optional[str] = None,
    ) -> None:
        """记录一次拉取失败 (status='failed')，不推翻既有成功记录。

        005-bloomberg-quota-pause: 额度爆满等场景下 Bloomberg 可能返回空响应
        或额度类错误，若把该日当作"已拉取"将导致缺数据且不重拉。此方法把
        失败写入 fetch_log.status='failed'，而 determine_fetch_range 只认
        'fetched'，故失败日期会留在缺口扫描中，额度恢复后自动重拉。

        与 add_fetch_log_record 的区别:
        - 不把同 source_date 旧 'fetched' 行标 'deprecated'（不推翻既有成功）
        - data_hash 用确定性占位 ("failed:" + reason)，保证可重入
        """
        conn = self._get_write_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            hash_placeholder = f"failed:{reason}"
            detail_suffix = f" ({detail})" if detail else ""
            conn.execute(
                "INSERT OR REPLACE INTO fetch_log "
                "(source_date, row_count, data_hash, file_path, status) "
                "VALUES (?, 0, ?, ?, 'failed')",
                (source_date, hash_placeholder, detail_suffix),
            )
            conn.commit()
            logger.warning(
                "Recorded fetch failure for %s (reason=%s%s)",
                source_date, reason, detail_suffix,
            )
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def upsert_order_fetch_log(
        self, fills: list[dict], source_date: str,
    ) -> None:
        """Record per-order fetch log entries."""
        if not fills:
            return
        conn = self._get_write_conn()
        try:
            seen = set()
            rows = []
            for f in fills:
                oid = f.get("OrderId", "")
                if oid and oid not in seen:
                    seen.add(oid)
                    rows.append((oid, source_date))
            conn.executemany(
                "INSERT OR IGNORE INTO order_fetch_log (order_id, source_date) VALUES (?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace cleaned fill records. Returns count of new rows."""
        if df.empty:
            return 0

        conn = self._get_write_conn()
        try:
            all_columns = ALL_RAW_COLUMNS + ["source_date", "ingested_at"]
            insert_columns = [c for c in all_columns if c in df.columns]
            placeholders = ", ".join(["?"] * len(insert_columns))
            col_names = ", ".join(insert_columns)
            sql = f"INSERT OR REPLACE INTO raw_fills ({col_names}) VALUES ({placeholders})"

            count_before = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]

            rows = []
            for tup in df[insert_columns].itertuples(index=False, name=None):
                values = []
                for i, col in enumerate(insert_columns):
                    val = tup[i]
                    if pd.isna(val) or val is None:
                        values.append(None)
                    else:
                        values.append(str(val))
                rows.append(tuple(values))

            conn.executemany(sql, rows)
            conn.commit()

            count_after = conn.execute("SELECT COUNT(*) FROM raw_fills").fetchone()[0]
            new_count = count_after - count_before
            logger.info(f"Upserted {len(rows)} fills ({new_count} new)")
            return new_count
        finally:
            conn.close()
