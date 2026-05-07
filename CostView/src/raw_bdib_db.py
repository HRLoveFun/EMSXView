"""
Raw BDIB SQLite storage.

.. deprecated::
    This module is superseded by `CostView.src.db.repositories.market_data_read`
    and `CostView.src.db.repositories.market_data_write`. New code should use
    the Repository implementations via `CostViewDatabase` facade. This file
    is retained for backward compatibility during pipeline migration.

Stores 10-second intraday BDIB bars as returned by Bloomberg blp.bdib().
Contains ONLY Bloomberg-native columns (OHLC/volume/num_trds/value).
No derived fields (vwap, fluctuation, etc.) — those belong in processed_bdib.

Schema matches D:\\Evaluation\\raw_data\\raw_bdib convention.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from .db.connection import AccessControlledConnection, AccessTier, resolve_access_tier
from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)

# ── Bloomberg-native BDIB columns (no derived fields) ──
RAW_BDIB_COLUMNS = [
    "equ_ticker",
    "order_as_of_date",
    "mkt_timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "num_trds",
    "value",
]


class RawBDIBDB:
    """SQLite storage for raw BDIB bars (Bloomberg-native columns only)."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
    ):
        self.db_path = Path(db_path or Config.RAW_BDIB_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_tier = resolve_access_tier(access_tier)
        self._init_db()

    def _get_conn(self) -> AccessControlledConnection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return AccessControlledConnection(conn, self._access_tier)

    def _get_admin_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        conn = self._get_admin_conn()
        try:
            # Only Bloomberg-native columns; NO derived fields (vwap, fluctuation, etc.)
            # Derived fields belong in processed_bdib per D:\Evaluation convention.
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.RAW_BDIB_TABLE} (
                    equ_ticker       TEXT NOT NULL,
                    order_as_of_date TEXT NOT NULL,
                    mkt_timestamp    TEXT NOT NULL,
                    open             REAL,
                    high             REAL,
                    low              REAL,
                    close            REAL,
                    volume           REAL,
                    num_trds         REAL,
                    value            REAL,
                    fetched_at       TEXT DEFAULT (datetime('now')),
                    source           TEXT DEFAULT 'bloomberg',
                    PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_date ON {Config.RAW_BDIB_TABLE} (order_as_of_date)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_ticker ON {Config.RAW_BDIB_TABLE} (equ_ticker)"
            )

            # Schema migration: add source column if missing (for existing DBs)
            cursor = conn.execute(f"PRAGMA table_info({Config.RAW_BDIB_TABLE})")
            existing_cols = {row[1] for row in cursor.fetchall()}
            if "source" not in existing_cols:
                conn.execute(
                    f"ALTER TABLE {Config.RAW_BDIB_TABLE} ADD COLUMN source TEXT DEFAULT 'bloomberg'"
                )
                logger.info("raw_bdib migration: added 'source' column")

            # bdib_daily_summary: per-ticker, per-date aggregated metrics for TCA
            # Stores Bloomberg daily fields plus locally-computed intraday carry-over metrics.
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.BDIB_DAILY_SUMMARY_TABLE} (
                    equ_ticker        TEXT NOT NULL,
                    trade_date        TEXT NOT NULL,
                    total_volume      REAL,
                    daily_vwap        REAL,
                    daily_close       REAL,
                    daily_volatility  REAL,
                    intraday_volatility REAL,
                    adv_5d            REAL,
                    adv_20d           REAL,
                    computed_at       TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (equ_ticker, trade_date)
                )
            """)
            summary_info = conn.execute(
                f"PRAGMA table_info({Config.BDIB_DAILY_SUMMARY_TABLE})"
            ).fetchall()
            summary_existing_cols = {row[1] for row in summary_info}
            for col_name, col_type in (
                ("daily_close", "REAL"),
                ("intraday_volatility", "REAL"),
            ):
                if col_name not in summary_existing_cols:
                    conn.execute(
                        f"ALTER TABLE {Config.BDIB_DAILY_SUMMARY_TABLE} "
                        f"ADD COLUMN {col_name} {col_type}"
                    )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_daily_summary_ticker "
                f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (equ_ticker)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_daily_summary_date "
                f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (trade_date)"
            )

            conn.commit()
        finally:
            conn.close()

    def upsert_bdib_data(self, df: pd.DataFrame, date_str: Optional[str] = None) -> int:
        """Upsert raw BDIB bars from DataFrame.

        Stores ONLY Bloomberg-native columns.
        Extra/derived columns in df are silently ignored.
        """
        if df is None or df.empty:
            return 0

        work = df.copy()
        if "order_as_of_date" not in work.columns:
            if "Order As of Date" in work.columns:
                work.rename(columns={"Order As of Date": "order_as_of_date"}, inplace=True)
            elif date_str:
                work["order_as_of_date"] = date_str
            else:
                raise ValueError("BDIB data missing order_as_of_date")

        required = ["equ_ticker", "order_as_of_date", "mkt_timestamp"]
        for col in required:
            if col not in work.columns:
                raise ValueError(f"BDIB data missing required column: {col}")

        # Only write Bloomberg-native columns — drop any derived fields that may be present
        cols = RAW_BDIB_COLUMNS.copy()
        # Include source column if present in input (e.g. fallback-derived data)
        if "source" in work.columns:
            cols.append("source")
        for col in cols:
            if col not in work.columns:
                work[col] = None

        # Ensure no extra columns leak into raw store (keep source if present)
        allowed = set(RAW_BDIB_COLUMNS) | {"source"}
        work = work[[c for c in cols if c in work.columns and c in allowed]]

        conn = self._get_conn()
        try:
            sql = f"""
                INSERT OR REPLACE INTO {Config.RAW_BDIB_TABLE}
                ({", ".join(cols)})
                VALUES ({", ".join(["?"] * len(cols))})
            """
            rows = [tuple(r) for r in work[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} raw BDIB rows ({len(RAW_BDIB_COLUMNS)} native cols)")
            return len(rows)
        finally:
            conn.close()

    def get_row_count(self) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def get_latest_order_as_of_date(self) -> Optional[str]:
        """Get latest order_as_of_date in raw_bdib (YYYYMMDD), or None if empty."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT MAX(order_as_of_date)
                    FROM {Config.RAW_BDIB_TABLE}
                    WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''"""
            )
            value = cursor.fetchone()[0]
            return str(value) if value else None
        finally:
            conn.close()

    # ── bdib_daily_summary CRUD ──────────────────────────────────────────────

    def upsert_daily_summary(self, rows: list[dict]) -> int:
        """Upsert pre-computed daily metrics into bdib_daily_summary.

        Each row dict must have: equ_ticker, trade_date.
        Optional: total_volume, daily_vwap, daily_close, daily_volatility,
        intraday_volatility, adv_5d, adv_20d.
        """
        if not rows:
            return 0
        cols = [
            "equ_ticker",
            "trade_date",
            "total_volume",
            "daily_vwap",
            "daily_close",
            "daily_volatility",
            "intraday_volatility",
            "adv_5d",
            "adv_20d",
        ]
        sql = (
            f"INSERT OR REPLACE INTO {Config.BDIB_DAILY_SUMMARY_TABLE} "
            f"({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
        )
        params = [
            tuple(r.get(c) for c in cols)
            for r in rows
        ]
        conn = self._get_conn()
        try:
            conn.executemany(sql, params)
            conn.commit()
            return len(params)
        finally:
            conn.close()

    def get_daily_summary(
        self,
        equ_ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Fetch bdib_daily_summary rows for a ticker over a date range."""
        conditions = ["equ_ticker = ?"]
        params: list = [equ_ticker]
        if start_date:
            conditions.append("trade_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("trade_date <= ?")
            params.append(end_date)
        where = " AND ".join(conditions)
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.BDIB_DAILY_SUMMARY_TABLE} WHERE {where} ORDER BY trade_date",
                conn._conn,
                params=params,
            )
            return df
        finally:
            conn.close()

    def get_latest_daily_summary(
        self,
        limit: int = 25,
        trade_date: Optional[str] = None,
    ) -> pd.DataFrame:
        """Return the latest available daily-summary rows for MarketView snapshots."""
        conn = self._get_conn()
        try:
            resolved_trade_date = trade_date
            if not resolved_trade_date:
                cursor = conn.execute(
                    f"SELECT MAX(trade_date) FROM {Config.BDIB_DAILY_SUMMARY_TABLE}"
                )
                resolved_trade_date = cursor.fetchone()[0]

            if not resolved_trade_date:
                return pd.DataFrame(
                    columns=[
                        "equ_ticker",
                        "trade_date",
                        "total_volume",
                        "daily_close",
                        "daily_volatility",
                        "intraday_volatility",
                        "adv_5d",
                        "adv_20d",
                    ]
                )

            return pd.read_sql_query(
                f"SELECT equ_ticker, trade_date, total_volume, daily_close, daily_volatility, "
                f"intraday_volatility, adv_5d, adv_20d "
                f"FROM {Config.BDIB_DAILY_SUMMARY_TABLE} "
                "WHERE trade_date = ? "
                "ORDER BY COALESCE(total_volume, 0) DESC, equ_ticker ASC "
                "LIMIT ?",
                conn._conn,
                params=[resolved_trade_date, limit],
            )
        finally:
            conn.close()

    def get_bdib_bars_for_date(
        self, equ_ticker: str, trade_date: str
    ) -> pd.DataFrame:
        """Fetch all 10s bars for a given ticker and date from raw_bdib."""
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_BDIB_TABLE} "
                "WHERE equ_ticker = ? AND order_as_of_date = ? "
                "ORDER BY mkt_timestamp",
                conn._conn,
                params=[equ_ticker, trade_date],
            )
            return df
        finally:
            conn.close()

    def get_bdib_bars_for_tickers_and_dates(
        self,
        equ_tickers: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch raw BDIB bars for multiple tickers over a date range."""
        if not equ_tickers:
            return pd.DataFrame()
        placeholders = ",".join(["?"] * len(equ_tickers))
        conn = self._get_conn()
        try:
            df = pd.read_sql_query(
                f"SELECT * FROM {Config.RAW_BDIB_TABLE} "
                f"WHERE equ_ticker IN ({placeholders}) "
                "AND order_as_of_date >= ? AND order_as_of_date <= ? "
                "ORDER BY equ_ticker, order_as_of_date, mkt_timestamp",
                conn._conn,
                params=[*equ_tickers, start_date, end_date],
            )
            return df
        finally:
            conn.close()

    def get_distinct_dates(self) -> list[str]:
        """Return all distinct order_as_of_date values in raw_bdib, sorted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"SELECT DISTINCT order_as_of_date FROM {Config.RAW_BDIB_TABLE} "
                "ORDER BY order_as_of_date"
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()
