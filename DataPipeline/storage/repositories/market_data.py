"""Market data repository — read/write access to raw_bdib.db and processed_raw_bdib.db.

Implements SqliteMarketDataReadRepository and SqliteMarketDataWriteRepository
using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from DataPipeline.config import Config
from ._base import RAW_BDIB_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


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
            return len(rows)
        finally:
            conn.close()

    def upsert_processed_bdib(self, df: pd.DataFrame) -> int:
        """Upsert processed/enhanced BDIB bars. Returns row count.

        Writes to processed_raw_bdib.db.
        """
        if df is None or df.empty:
            return 0

        from DataPipeline.storage.processed_raw_bdib_db import PROCESSED_RAW_BDIB_COLUMNS
        cols = list(PROCESSED_RAW_BDIB_COLUMNS)
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
