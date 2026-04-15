"""
Raw BDIB SQLite storage.

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

from .database_access import AccessControlledConnection, AccessTier, resolve_access_tier
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
                    PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_date ON {Config.RAW_BDIB_TABLE} (order_as_of_date)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_ticker ON {Config.RAW_BDIB_TABLE} (equ_ticker)"
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
        for col in cols:
            if col not in work.columns:
                work[col] = None

        # Ensure no extra columns leak into raw store
        work = work[[c for c in RAW_BDIB_COLUMNS if c in work.columns]]

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
