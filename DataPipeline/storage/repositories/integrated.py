"""Integrated repository — read/write access to fill_bdib.db.

Implements IntegratedReadRepository and IntegratedWriteRepository
Protocols using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from DataPipeline.config import Config
from DataPipeline.storage.schema.columns import COLUMN_TYPE_MAP, TCA_ROUTE_SUMMARY_COLUMNS
from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteIntegratedReadRepository(BaseRepository):
    """Read access to fill+BDIB integrated data."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="fill_bdib")

    def get_integrated_data_for_date(self, date_str: str) -> pd.DataFrame:
        """Return integrated fills+BDIB rows for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.FILL_BDIB_TABLE} WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_row_count(self) -> int:
        """Return total rows."""
        conn = self._get_read_conn()
        try:
            return int(conn.execute(
                f"SELECT COUNT(*) FROM {Config.FILL_BDIB_TABLE}"
            ).fetchone()[0])
        finally:
            conn.close()


class SqliteIntegratedWriteRepository(BaseRepository):
    """Write access to fill+BDIB integrated data."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="fill_bdib")

    def upsert_integrated_data(
        self, df: pd.DataFrame, date_str: Optional[str] = None,
    ) -> int:
        """Upsert integrated fill+BDIB data. Returns row count."""
        if df is None or df.empty:
            return 0

        stored_cols = [
            "OrderId", "RouteId", "order_as_of_date", "mkt_timestamp",
            "equ_ticker", "ccy_ticker", "fill_volume", "fill_px",
            "open", "high", "low", "close", "volume", "value", "vwap",
            "log_chg_pct_10s", "fx_rate", "cum_vwap", "cum_fill_vwap",
            "cum_slippage_bps", "cum_slippage_usd", "cum_volume_pct",
            "cum_tracking_error", "cum_info_ratio", "cum_interval_volatility",
            "standard_cum_interval_volatility",
        ]
        insert_cols = [c for c in stored_cols if c in df.columns]
        if not insert_cols:
            return 0

        placeholders = ", ".join(["?"] * len(insert_cols))
        col_names = ", ".join(insert_cols)
        sql = (
            f"INSERT OR REPLACE INTO {Config.FILL_BDIB_TABLE} "
            f"({col_names}) VALUES ({placeholders})"
        )

        conn = self._get_write_conn()
        try:
            rows = []
            for tup in df[insert_cols].itertuples(index=False, name=None):
                values = []
                for i, col in enumerate(insert_cols):
                    val = tup[i]
                    if val is None or (isinstance(val, float) and val != val):
                        values.append(None)
                    else:
                        values.append(val)
                rows.append(tuple(values))
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} fill_bdib rows")
            return len(rows)
        finally:
            conn.close()

    def upsert_tca_route_summary(
        self, df: pd.DataFrame, date_str: Optional[str] = None,
    ) -> int:
        """Upsert tca_route_summary rows. Returns row count."""
        if df is None or df.empty:
            return 0

        insert_cols = [c for c in TCA_ROUTE_SUMMARY_COLUMNS if c in df.columns]
        if not insert_cols:
            return 0

        placeholders = ", ".join(["?"] * len(insert_cols))
        col_names = ", ".join(insert_cols)
        sql = (
            f"INSERT OR REPLACE INTO {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"({col_names}) VALUES ({placeholders})"
        )

        conn = self._get_write_conn()
        try:
            rows = []
            for tup in df[insert_cols].itertuples(index=False, name=None):
                values = []
                for i, col in enumerate(insert_cols):
                    val = tup[i]
                    if val is None or (isinstance(val, float) and val != val):
                        values.append(None)
                    elif col in COLUMN_TYPE_MAP and COLUMN_TYPE_MAP[col] == "REAL":
                        values.append(float(val) if val is not None else None)
                    elif col in COLUMN_TYPE_MAP and COLUMN_TYPE_MAP[col] == "INTEGER":
                        values.append(int(val) if val is not None else None)
                    else:
                        values.append(str(val) if val is not None else None)
                rows.append(tuple(values))
            conn.executemany(sql, rows)
            conn.commit()
            logger.info(f"Upserted {len(rows)} tca_route_summary rows")
            return len(rows)
        finally:
            conn.close()

