"""Market data repository — read/write access to raw_bdib.db and processed_raw_bdib.db.

Implements SqliteMarketDataReadRepository and SqliteMarketDataWriteRepository
using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from DataPipeline.config import Config
from ._base import RAW_BDIB_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)

_parquet_writer = None


def _get_parquet_writer():
    global _parquet_writer
    if _parquet_writer is None and Config.BDIB_PARQUET_ENABLED:
        from DataPipeline.storage.market_store import MarketStoreWriter
        _parquet_writer = MarketStoreWriter(Config.BDIB_PARQUET_DIR)
    return _parquet_writer


class SqliteMarketDataReadRepository(BaseRepository):
    """Read access to BDIB bars and daily summaries."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="raw_bdib")

    def get_bdib_bars_for_date(
        self, equ_ticker: str, trade_date: str,
    ) -> pd.DataFrame:
        """Return 10s bars for a ticker+date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM raw_bdib "
                "WHERE equ_ticker = ? AND order_as_of_date = ? "
                "ORDER BY mkt_timestamp",
                conn.raw_connection,
                params=[equ_ticker, trade_date],
            )
        finally:
            conn.close()

    def get_bdib_bars_for_tickers_and_dates(
        self, equ_tickers: List[str], start_date: str, end_date: str,
    ) -> pd.DataFrame:
        """Return bars for multiple tickers over a date range."""
        if not equ_tickers:
            return pd.DataFrame()
        placeholders = ",".join(["?"] * len(equ_tickers))
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM raw_bdib "
                f"WHERE equ_ticker IN ({placeholders}) "
                "AND order_as_of_date >= ? AND order_as_of_date <= ? "
                "ORDER BY equ_ticker, order_as_of_date, mkt_timestamp",
                conn.raw_connection,
                params=[*equ_tickers, start_date, end_date],
            )
        finally:
            conn.close()

    def get_latest_order_as_of_date(self) -> Optional[str]:
        """Return latest date in raw_bdib."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT MAX(order_as_of_date) FROM raw_bdib "
                "WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''"
            )
            value = cursor.fetchone()[0]
            return str(value) if value else None
        finally:
            conn.close()

    def get_daily_summary(
        self, equ_ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return bdib_daily_summary rows for a ticker."""
        conditions = ["equ_ticker = ?"]
        params: list = [equ_ticker]
        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)
        where = " AND ".join(conditions)
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM bdib_daily_summary WHERE {where} ORDER BY trade_date",
                conn.raw_connection,
                params=params,
            )
        finally:
            conn.close()

    def get_daily_summary_for_date(
        self, trade_date: str,
    ) -> pd.DataFrame:
        """Return all bdib_daily_summary rows for a given trade_date.

        用于 TCA 路由指标计算（003-tca-core-benchmarks）：按交易日一次性
        读取全部 ticker 的 daily_close，避免逐 ticker 查询的 N+1 开销。
        trade_date 兼容 YYYYMMDD 与 YYYY-MM-DD 两种格式（做前缀匹配）。
        """
        conn = self._get_read_conn()
        try:
            compact = trade_date.replace("-", "")
            rows = pd.read_sql_query(
                "SELECT * FROM bdib_daily_summary ORDER BY trade_date",
                conn.raw_connection,
            )
            if rows.empty:
                return rows
            rows["_trade_date_compact"] = (
                rows["trade_date"].astype(str).str.replace("-", "", regex=False)
            )
            matched = rows[rows["_trade_date_compact"] == compact]
            return matched.drop(columns=["_trade_date_compact"])
        finally:
            conn.close()

    def get_daily_summary_for_date_range(
        self, start_date: str, end_date: str,
        equ_tickers: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Return bdib_daily_summary rows within [start_date, end_date].

        003-tca-core-benchmarks: TCA 路由指标计算需一次加载区间内全部 ticker
        的 daily_close（当日收盘基准 + 跨日次日收盘恢复窗口），避免逐 ticker
        N+1 查询。trade_date 兼容 YYYYMMDD 与 YYYY-MM-DD 两种格式。
        """
        conn = self._get_read_conn()
        try:
            rows = pd.read_sql_query(
                "SELECT * FROM bdib_daily_summary ORDER BY trade_date",
                conn.raw_connection,
            )
            if rows.empty:
                return rows
            rows["_trade_date_compact"] = (
                rows["trade_date"].astype(str).str.replace("-", "", regex=False)
            )
            start_compact = start_date.replace("-", "")
            end_compact = end_date.replace("-", "")
            mask = (rows["_trade_date_compact"] >= start_compact) & (
                rows["_trade_date_compact"] <= end_compact
            )
            if equ_tickers:
                mask = mask & rows["equ_ticker"].isin(equ_tickers)
            matched = rows[mask]
            return matched.drop(columns=["_trade_date_compact"])
        finally:
            conn.close()

    def get_latest_daily_summary(
        self, limit: int = 25, trade_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return latest daily-summary rows."""
        conn = self._get_read_conn()
        try:
            resolved = trade_date
            if not resolved:
                cursor = conn.execute(
                    "SELECT MAX(trade_date) FROM bdib_daily_summary"
                )
                resolved = cursor.fetchone()[0]
            if not resolved:
                return pd.DataFrame()
            return pd.read_sql_query(
                "SELECT equ_ticker, trade_date, total_volume, daily_close, "
                "daily_volatility, intraday_volatility, adv_5d, adv_20d "
                "FROM bdib_daily_summary "
                "WHERE trade_date = ? "
                "ORDER BY COALESCE(total_volume, 0) DESC, equ_ticker ASC "
                "LIMIT ?",
                conn.raw_connection,
                params=[resolved, limit],
            )
        finally:
            conn.close()

    def get_distinct_dates(self) -> List[str]:
        """Return distinct order_as_of_date values."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM raw_bdib ORDER BY order_as_of_date"
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_row_count(self) -> int:
        """Return total rows in raw_bdib."""
        conn = self._get_read_conn()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM raw_bdib").fetchone()[0])
        finally:
            conn.close()


class SqliteMarketDataWriteRepository(BaseRepository):
    """Write access to BDIB bars and daily summaries.

    Handles writes to both raw_bdib.db and processed_raw_bdib.db.
    The database parameter selects which database to write to.
    """

    def __init__(self, connection_manager=None, database: str = "raw_bdib"):
        super().__init__(connection_manager, database=database)

    @staticmethod
    def compute_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "close" not in df.columns:
            return df
        result = df.copy()
        if "value" in result.columns and "volume" in result.columns:
            safe_vol = result["volume"].fillna(0).replace(0, np.nan)
            result["vwap"] = np.where(
                safe_vol > 0,
                result["value"] / safe_vol,
                result["close"],
            )
        elif "close" in result.columns:
            result["vwap"] = result["close"]
        if all(c in result.columns for c in ("high", "low", "close")):
            safe_close = result["close"].replace(0, np.nan)
            result["fluctuation"] = (
                (result["high"].fillna(result["close"])
                 - result["low"].fillna(result["close"]))
                / safe_close
            ).fillna(0)
        if "close" in result.columns:
            result["log_chg_pct_10s"] = (
                np.log(result["close"] / result["close"].shift(1)).fillna(0)
            )
        return result

    def upsert_bdib_data(
        self, df: pd.DataFrame, date_str: Optional[str] = None,
    ) -> int:
        """Upsert raw BDIB bars. Returns row count."""
        if df is None or df.empty:
            return 0

        work = df.copy()
        if "order_as_of_date" not in work.columns:
            if "Order As of Date" in work.columns:
                work.rename(columns={"Order As of Date": "order_as_of_date"}, inplace=True)
            elif date_str:
                work["order_as_of_date"] = date_str

        cols = list(RAW_BDIB_COLUMNS)
        if "source" in work.columns:
            cols.append("source")
        for col in cols:
            if col not in work.columns:
                work[col] = None

        allowed = set(RAW_BDIB_COLUMNS) | {"source"}
        work = work[[c for c in cols if c in work.columns and c in allowed]]

        conn = self._get_write_conn()
        try:
            sql = (
                f"INSERT OR REPLACE INTO {Config.RAW_BDIB_TABLE} "
                f"({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
            )
            rows = [tuple(r) for r in work[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} raw BDIB rows")

            writer = _get_parquet_writer()
            if writer is not None:
                try:
                    pq_rows = writer.write_batch(work)
                    logger.debug(f"Parquet双写: {pq_rows}行")
                except Exception as e:
                    logger.warning(f"Parquet双写失败 (不影响SQLite主路径): {e}")

            return len(rows)
        finally:
            conn.close()

    def upsert_processed_bdib(self, df: pd.DataFrame) -> int:
        """Upsert processed/enhanced BDIB bars. Returns row count.

        Writes to processed_raw_bdib.db.
        由 PROCESSED_RAW_BDIB_ENABLED 控制 — A8退役后停止写入。
        """
        if df is None or df.empty:
            return 0
        if not Config.PROCESSED_RAW_BDIB_ENABLED:
            return 0

        cols = [
            "equ_ticker", "order_as_of_date", "mkt_timestamp",
            "open", "high", "low", "close", "volume", "num_trds",
            "value", "vwap", "fluctuation", "log_chg_pct_10s",
        ]
        for col in cols:
            if col not in df.columns:
                return 0

        mgr = self._mgr
        conn = mgr.get_connection("processed_raw_bdib")
        try:
            sql = (
                f"INSERT OR REPLACE INTO {Config.PROCESSED_RAW_BDIB_TABLE} "
                f"({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
            )
            rows = [tuple(r) for r in df[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} processed BDIB rows")
            return len(rows)
        finally:
            conn.close()

    def upsert_daily_summary(self, rows: List[Dict]) -> int:
        """Upsert daily metrics. Returns row count."""
        if not rows:
            return 0
        cols = [
            "equ_ticker", "trade_date", "total_volume", "daily_vwap",
            "daily_close", "daily_volatility", "intraday_volatility",
            "adv_5d", "adv_20d",
        ]
        sql = (
            f"INSERT OR REPLACE INTO {Config.BDIB_DAILY_SUMMARY_TABLE} "
            f"({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
        )
        params = [tuple(r.get(c) for c in cols) for r in rows]
        conn = self._get_write_conn()
        try:
            conn.executemany(sql, params)
            conn.commit()
            return len(params)
        finally:
            conn.close()
