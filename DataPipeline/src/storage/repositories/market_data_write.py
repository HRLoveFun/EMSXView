"""Market data write repository — write access to raw_bdib.db + processed_raw_bdib.db.

Implements MarketDataWriteRepository Protocol using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.storage.raw_bdib_db import RAW_BDIB_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


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

        from DataPipeline.src.storage.processed_raw_bdib_db import PROCESSED_RAW_BDIB_COLUMNS
        cols = list(PROCESSED_RAW_BDIB_COLUMNS)
        for col in cols:
            if col not in df.columns:
                return 0

        # Switch to processed_raw_bdib database
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
