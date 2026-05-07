"""
Fill-BDIB Integrated SQLite storage.

.. deprecated::
    This module is superseded by `CostView.src.db.repositories.integrated`.
    New code should use the Repository implementations via `CostViewDatabase`
    facade. This file is retained for backward compatibility during pipeline
    migration.

Stores integrated fills+BDIB/TCA rows keyed by
(OrderId, RouteId, order_as_of_date, mkt_timestamp).

This corresponds to D:\\Evaluation\\processed_data\\processed_fills_bdib convention.
It is the final output of the BDIB pipeline — fills merged with market data,
enriched with TCA metrics (slippage, tracking error, info ratio, etc.).
"""

from __future__ import annotations

import logging
import sqlite3
import warnings
from pathlib import Path
from typing import Optional

import pandas as pd

from DataPipeline.src.storage.connection import AccessControlledConnection, AccessTier, ConnectionManager, resolve_access_tier
from DataPipeline.src.common.processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


class FillBDIBDB:
    """SQLite storage for integrated fills+BDIB/TCA output.

    Corresponds to D:\\Evaluation's "fill_bdib" (processed_fills_bdib) concept.
    """

    KEY_COLUMNS = ["OrderId", "RouteId", "order_as_of_date", "mkt_timestamp"]

    STORED_COLUMNS = [
        "OrderId",
        "RouteId",
        "order_as_of_date",
        "mkt_timestamp",
        "equ_ticker",
        "ccy_ticker",
        "fill_volume",
        "fill_px",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "value",
        "vwap",
        "log_chg_pct_10s",
        "fx_rate",
        "cum_vwap",
        "cum_fill_vwap",
        "cum_slippage_bps",
        "cum_slippage_usd",
        "cum_volume_pct",
        "cum_tracking_error",
        "cum_info_ratio",
        "cum_interval_volatility",
        "standard_cum_interval_volatility",
    ]

    def __init__(
        self,
        db_path: Optional[str] = None,
        access_tier: Optional[AccessTier] = None,
        connection_manager: Optional[ConnectionManager] = None,
    ):
        warnings.warn(
            "FillBDIBDB is deprecated. Use CostViewDatabase facade or "
            "db.repositories.integrated via ConnectionManager. "
            "See docs/spec/data-domain.md for the Data Platform extraction roadmap.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.db_path = Path(db_path or Config.FILL_BDIB_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._access_tier = resolve_access_tier(access_tier)
        if connection_manager is not None:
            self._mgr = connection_manager
        else:
            overrides = {"fill_bdib": self.db_path} if db_path else {}
            self._mgr = ConnectionManager(path_overrides=overrides)
        self._init_db()

    def _get_conn(self) -> AccessControlledConnection:
        return self._mgr.get_connection("fill_bdib", self._access_tier)

    def _get_admin_conn(self) -> sqlite3.Connection:
        return self._mgr.get_admin_connection("fill_bdib")

    def _init_db(self) -> None:
        conn = self._get_admin_conn()
        try:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {Config.FILL_BDIB_TABLE} (
                    OrderId                          TEXT NOT NULL,
                    RouteId                          TEXT NOT NULL,
                    order_as_of_date                 TEXT NOT NULL,
                    mkt_timestamp                    TEXT NOT NULL,
                    equ_ticker                       TEXT,
                    ccy_ticker                       TEXT,
                    fill_volume                       REAL,
                    fill_px                           REAL,
                    open                              REAL,
                    high                              REAL,
                    low                               REAL,
                    close                             REAL,
                    volume                            REAL,
                    value                             REAL,
                    vwap                              REAL,
                    log_chg_pct_10s                   REAL,
                    fx_rate                           REAL,
                    cum_vwap                          REAL,
                    cum_fill_vwap                     REAL,
                    cum_slippage_bps                  REAL,
                    cum_slippage_usd                  REAL,
                    cum_volume_pct                    REAL,
                    cum_tracking_error                REAL,
                    cum_info_ratio                   REAL,
                    cum_interval_volatility           REAL,
                    standard_cum_interval_volatility   REAL,
                    PRIMARY KEY (OrderId, RouteId, order_as_of_date, mkt_timestamp)
                )
            """)
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fill_bdib_date ON {Config.FILL_BDIB_TABLE} (order_as_of_date)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_fill_bdib_ticker ON {Config.FILL_BDIB_TABLE} (equ_ticker)"
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_integrated_data(self, df: pd.DataFrame, date_str: Optional[str] = None) -> int:
        """Upsert integrated fills+BDIB/TCA rows."""
        if df is None or df.empty:
            return 0

        work = df.copy()
        if "order_as_of_date" not in work.columns and date_str:
            work["order_as_of_date"] = date_str

        for col in self.KEY_COLUMNS:
            if col not in work.columns:
                raise ValueError(f"Fill-BDIB data missing required key column: {col}")

        for col in self.STORED_COLUMNS:
            if col not in work.columns:
                work[col] = None

        conn = self._get_conn()
        try:
            sql = f"""
                INSERT OR REPLACE INTO {Config.FILL_BDIB_TABLE}
                ({", ".join(self.STORED_COLUMNS)})
                VALUES ({", ".join(["?"] * len(self.STORED_COLUMNS))})
            """
            rows = [tuple(r) for r in work[self.STORED_COLUMNS].itertuples(index=False, name=None)]
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} fill-bdib rows")
            return len(rows)
        finally:
            conn.close()

    def get_row_count(self) -> int:
        conn = self._get_conn()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE}")
            return int(cursor.fetchone()[0])
        finally:
            conn.close()
