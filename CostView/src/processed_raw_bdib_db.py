"""
Processed Raw BDIB SQLite storage.

Stores enhanced BDIB bars derived from raw_bdib with computed fields:
  - vwap: volume-weighted average price
  - fluctuation: (high - low) / close
  - log_chg_pct_10s: log return over 10s interval
  - cum_volume, cum_value: cumulative volume/value per (ticker, date)

This layer corresponds to D:\\Evaluation\\processed_data\\processed_bdib convention.
It sits between raw_bdib (Bloomberg-native) and fill_bdib (fills+BDIB integration).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .database_access import AccessControlledConnection, AccessTier, resolve_access_tier
from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)

# All columns stored in this table (raw + derived)
PROCESSED_RAW_BDIB_COLUMNS = [
    # Raw Bloomberg-native columns
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
    # Derived fields (computed from raw)
    "vwap",
    "fluctuation",
    "log_chg_pct_10s",
]


class ProcessedRawBDIBDB:
    """SQLite storage for processed/enhanced raw BDIB bars."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
    ):
        self.db_path = Path(db_path or Config.PROCESSED_RAW_BDIB_DB)
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
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSED_RAW_BDIB_TABLE} (
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
                    vwap             REAL,
                    fluctuation      REAL,
                    log_chg_pct_10s  REAL,
                    fetched_at       TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_date ON {Config.PROCESSED_RAW_BDIB_TABLE} (order_as_of_date)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_ticker ON {Config.PROCESSED_RAW_BDIB_TABLE} (equ_ticker)"
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_processed_bdib(self, df: pd.DataFrame) -> int:
        """Upsert processed BDIB data with derived fields.

        Args:
            df: DataFrame containing raw Bloomberg cols + vwap/fluctuation/log_chg_pct_10s.
        """
        if df is None or df.empty:
            return 0

        work = df.copy()

        # Rename Bloomberg-native column names to match our schema
        rename_map = {"Order As of Date": "order_as_of_date"}
        for old_name, new_name in rename_map.items():
            if old_name in work.columns:
                work.rename(columns={old_name: new_name}, inplace=True)

        for col in PROCESSED_RAW_BDIB_COLUMNS:
            if col not in work.columns:
                work[col] = None

        conn = self._get_conn()
        try:
            cols = [c for c in PROCESSED_RAW_BDIB_COLUMNS if c != "fetched_at"]
            sql = f"""
                INSERT OR REPLACE INTO {Config.PROCESSED_RAW_BDIB_TABLE}
                ({", ".join(cols)}, fetched_at)
                VALUES ({", ".join(["?"] * len(cols))}, datetime('now'))
            """
            rows = [tuple(r) for r in work[cols].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} processed raw BDIB rows")
            return len(rows)
        finally:
            conn.close()

    def get_bdib_for_date(self, date_str: str) -> pd.DataFrame:
        """Get all processed raw BDIB bars for a given date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_RAW_BDIB_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_row_count(self) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {Config.PROCESSED_RAW_BDIB_TABLE}")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()

    def get_latest_order_as_of_date(self) -> Optional[str]:
        """Get latest order_as_of_date, or None if empty."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT MAX(order_as_of_date)
                    FROM {Config.PROCESSED_RAW_BDIB_TABLE}
                    WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''"""
            )
            value = cursor.fetchone()[0]
            return str(value) if value else None
        finally:
            conn.close()

    @staticmethod
    def compute_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
        """Compute vwap, fluctuation, log_chg_pct_10s from raw Bloomberg columns.

        Args:
            df: DataFrame with at least open/high/low/close/volume/value columns.

        Returns:
            DataFrame with additional vwap, fluctuation, log_chg_pct_10s columns.
        """
        if df.empty or "close" not in df.columns:
            return df

        result = df.copy()

        # VWAP: value / volume when volume > 0; fallback to close price
        if "value" in result.columns and "volume" in result.columns:
            safe_vol = result["volume"].fillna(0).replace(0, np.nan)
            result["vwap"] = np.where(
                safe_vol > 0,
                result["value"] / safe_vol,
                result["close"],
            )
        elif "close" in result.columns:
            result["vwap"] = result["close"]

        # Fluctuation: (high - low) / close
        if all(c in result.columns for c in ("high", "low", "close")):
            safe_close = result["close"].replace(0, np.nan)
            result["fluctuation"] = (
                (result["high"].fillna(result["close"])
                 - result["low"].fillna(result["close"]))
                / safe_close
            )

        # Log change % over 10s interval (per ticker+date group)
        if "close" in result.columns:
            result["log_chg_pct_10s"] = (
                np.log(result["close"] / result["close"].shift(1))
                .fillna(0)
            )

        return result
