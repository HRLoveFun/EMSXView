"""
Processed Fills SQLite Database.

Stores processed fill data (with algo, ccy_ticker, equ_ticker, mkt_timestamp, etc.),
aggregated fills, and processing log. Provides date-based querying and incremental
upsert semantics.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from .processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


class ProcessedFillsDB:
    """SQLite storage for processed EMSX fill data."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or Config.PROCESSED_FILLS_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            # processed_fills: dynamic schema — we create it based on first insert
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
                    OrderId TEXT NOT NULL,
                    FillId TEXT NOT NULL,
                    PRIMARY KEY (OrderId, FillId)
                )
            """)

            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_proc_fills_date
                ON {Config.PROCESSED_FILLS_TABLE} (order_as_of_date)
            """)

            # processing_log: track which dates have been processed
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSING_LOG_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_as_of_date TEXT NOT NULL,
                    processing_timestamp TEXT DEFAULT (datetime('now')),
                    row_count INTEGER,
                    stage TEXT DEFAULT 'processed',
                    UNIQUE(order_as_of_date, stage)
                )
            """)

            # ticker_date_mapping: equ_ticker/ccy_ticker → dates
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.TICKER_DATE_MAPPING_TABLE} (
                    ticker TEXT NOT NULL,
                    ticker_type TEXT NOT NULL,
                    order_as_of_date TEXT NOT NULL,
                    PRIMARY KEY (ticker, ticker_type, order_as_of_date)
                )
            """)

            # agg_processed_fills: 10-second aggregated fills
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.AGG_PROCESSED_FILLS_TABLE} (
                    OrderId TEXT NOT NULL,
                    mkt_timestamp TEXT NOT NULL,
                    order_as_of_date TEXT,
                    PRIMARY KEY (OrderId, mkt_timestamp, order_as_of_date)
                )
            """)

            # processed_fills_1min: 1-minute aggregated fills
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_1MIN_TABLE} (
                    OrderId TEXT NOT NULL,
                    mkt_timestamp_1min TEXT NOT NULL,
                    order_as_of_date TEXT,
                    PRIMARY KEY (OrderId, mkt_timestamp_1min, order_as_of_date)
                )
            """)

            # order_label
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.ORDER_LABEL_TABLE} (
                    OrderId TEXT PRIMARY KEY,
                    order_as_of_date TEXT
                )
            """)

            conn.commit()
            logger.debug(f"Processed fills DB initialized at {self.db_path}")
        finally:
            conn.close()

    # ── Generic DataFrame write ─────────────────────────────────────────────

    def _upsert_df_to_table(
        self,
        df: pd.DataFrame,
        table_name: str,
        key_columns: List[str],
    ) -> int:
        """Insert or replace a DataFrame into a table, dynamically adding columns."""
        if df.empty:
            return 0

        conn = self._get_conn()
        try:
            # Get existing columns
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            existing_cols = {row[1] for row in cursor.fetchall()}

            # Add missing columns dynamically
            for col in df.columns:
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN [{col}] TEXT")
                    logger.debug(f"Added column [{col}] to {table_name}")

            # Build INSERT OR REPLACE
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

    # ── Processed Fills ─────────────────────────────────────────────────────

    def upsert_processed_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace processed fill records."""
        count = self._upsert_df_to_table(
            df, Config.PROCESSED_FILLS_TABLE, ["OrderId", "FillId"]
        )
        logger.info(f"Upserted {count} processed fills")
        return count

    def get_processed_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Get processed fills for a specific order_as_of_date."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_processed_fills_for_date_range(self, start: str, end: str) -> pd.DataFrame:
        """Get processed fills for a date range (inclusive, YYYYMMDD)."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"""SELECT * FROM {Config.PROCESSED_FILLS_TABLE}
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, mkt_timestamp""",
                conn,
                params=[start, end],
            )
        finally:
            conn.close()

    def get_all_processed_fills(self) -> pd.DataFrame:
        """Get all processed fills."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_FILLS_TABLE}", conn
            )
        finally:
            conn.close()

    # ── Aggregated Fills ────────────────────────────────────────────────────

    def upsert_agg_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace 10-second aggregated fill records."""
        count = self._upsert_df_to_table(
            df, Config.AGG_PROCESSED_FILLS_TABLE, ["OrderId", "mkt_timestamp", "order_as_of_date"]
        )
        logger.info(f"Upserted {count} aggregated fills (10s)")
        return count

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.AGG_PROCESSED_FILLS_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── 1-Minute Aggregation ────────────────────────────────────────────────

    def upsert_1min_fills(self, df: pd.DataFrame) -> int:
        """Insert or replace 1-minute aggregated fill records."""
        count = self._upsert_df_to_table(
            df, Config.PROCESSED_FILLS_1MIN_TABLE, ["OrderId", "mkt_timestamp_1min", "order_as_of_date"]
        )
        logger.info(f"Upserted {count} aggregated fills (1min)")
        return count

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.PROCESSED_FILLS_1MIN_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Order Labels ────────────────────────────────────────────────────────

    def upsert_order_labels(self, df: pd.DataFrame) -> int:
        """Insert or replace order label records."""
        count = self._upsert_df_to_table(
            df, Config.ORDER_LABEL_TABLE, ["OrderId"]
        )
        logger.info(f"Upserted {count} order labels")
        return count

    def get_order_labels(self) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE}", conn
            )
        finally:
            conn.close()

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.ORDER_LABEL_TABLE} WHERE order_as_of_date = ?",
                conn,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Processing Log ──────────────────────────────────────────────────────

    def mark_date_processed(self, date_str: str, stage: str = "processed", row_count: int = 0) -> None:
        """Record that a date has been processed at a given stage."""
        conn = self._get_conn()
        try:
            conn.execute(
                f"""INSERT OR REPLACE INTO {Config.PROCESSING_LOG_TABLE}
                    (order_as_of_date, row_count, stage)
                    VALUES (?, ?, ?)""",
                (date_str, row_count, stage),
            )
            conn.commit()
        finally:
            conn.close()

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Get all dates that have been processed at a given stage."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT DISTINCT order_as_of_date
                    FROM {Config.PROCESSING_LOG_TABLE}
                    WHERE stage = ?
                    ORDER BY order_as_of_date""",
                (stage,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_unprocessed_dates(self, raw_dates: List[str], stage: str = "processed") -> List[str]:
        """Get dates from raw_dates that haven't been processed at the given stage."""
        processed = set(self.get_processed_dates(stage))
        return [d for d in raw_dates if d not in processed]

    # ── Ticker-Date Mapping ─────────────────────────────────────────────────

    def update_ticker_date_mapping(self, df: pd.DataFrame) -> None:
        """Update ticker→date mapping from processed fills DataFrame."""
        if df.empty:
            return

        conn = self._get_conn()
        try:
            records = []

            # Equity tickers
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("equ_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "equ_ticker", str(date_str)))

            # Currency tickers
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("ccy_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "ccy_ticker", str(date_str)))

            if records:
                conn.executemany(
                    f"""INSERT OR IGNORE INTO {Config.TICKER_DATE_MAPPING_TABLE}
                        (ticker, ticker_type, order_as_of_date) VALUES (?, ?, ?)""",
                    records,
                )
                conn.commit()
                logger.debug(f"Updated ticker-date mapping: {len(records)} entries")
        finally:
            conn.close()

    def get_ticker_dates(self, ticker_type: str = "equ_ticker") -> Dict[str, List[str]]:
        """Get ticker→dates mapping."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                f"""SELECT ticker, order_as_of_date
                    FROM {Config.TICKER_DATE_MAPPING_TABLE}
                    WHERE ticker_type = ?
                    ORDER BY ticker, order_as_of_date""",
                (ticker_type,),
            )
            result: Dict[str, List[str]] = {}
            for ticker, date_str in cursor.fetchall():
                result.setdefault(ticker, []).append(date_str)
            return result
        finally:
            conn.close()

    # ── Stats ───────────────────────────────────────────────────────────────

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all tables."""
        conn = self._get_conn()
        try:
            stats = {}
            for table in [
                Config.PROCESSED_FILLS_TABLE,
                Config.AGG_PROCESSED_FILLS_TABLE,
                Config.PROCESSED_FILLS_1MIN_TABLE,
                Config.ORDER_LABEL_TABLE,
            ]:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    stats[table] = 0

            # Processing log dates
            try:
                cursor = conn.execute(
                    f"""SELECT stage, COUNT(DISTINCT order_as_of_date)
                        FROM {Config.PROCESSING_LOG_TABLE}
                        GROUP BY stage"""
                )
                stats["processing_stages"] = {r[0]: r[1] for r in cursor.fetchall()}
            except sqlite3.OperationalError:
                stats["processing_stages"] = {}

            return stats
        finally:
            conn.close()
