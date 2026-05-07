"""Fill read repository — read access to processed_fills.db.

Implements FillReadRepository Protocol using ConnectionManager.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

import pandas as pd

from ..connection import AccessTier
from ._base import BaseRepository

logger = logging.getLogger(__name__)


class SqliteFillReadRepository(BaseRepository):
    """Read access to processed fills, route registry, and aggregations."""

    def __init__(self, connection_manager=None):
        super().__init__(connection_manager, database="processed_fills")

    def get_fills_for_date(self, yyyymmdd: str) -> pd.DataFrame:
        """Return processed fills for a trading date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[yyyymmdd],
            )
        finally:
            conn.close()

    def get_all_processed_fills(self) -> pd.DataFrame:
        """Return all processed fills."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills", conn.raw_connection,
            )
        finally:
            conn.close()

    def get_distinct_dates_in_range(
        self, start_yyyymmdd: str, end_yyyymmdd: str,
    ) -> List[str]:
        """Return sorted list of distinct order_as_of_date values with fills."""
        conn = self._get_read_conn()
        try:
            df = pd.read_sql_query(
                "SELECT DISTINCT order_as_of_date FROM processed_fills "
                "WHERE order_as_of_date BETWEEN ? AND ? "
                "  AND ExecType='FILL' AND FillShares>0 AND FillPrice>0 "
                "ORDER BY order_as_of_date",
                conn.raw_connection,
                params=(start_yyyymmdd, end_yyyymmdd),
            )
            return df["order_as_of_date"].tolist()
        finally:
            conn.close()

    def get_processed_dates(self, stage: str = "processed") -> List[str]:
        """Return dates that have been processed for a given stage."""
        conn = self._get_read_conn()
        try:
            cursor = conn.execute(
                "SELECT DISTINCT order_as_of_date FROM processing_log "
                "WHERE stage = ? ORDER BY order_as_of_date",
                (stage,),
            )
            return [r[0] for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_unprocessed_dates(
        self, candidate_dates: List[str], stage: str = "processed",
    ) -> List[str]:
        """Return dates from candidates that have not been processed for a stage."""
        processed = set(self.get_processed_dates(stage))
        return [d for d in candidate_dates if d not in processed]

    def get_agg_fills_10s_for_date(self, date_str: str) -> pd.DataFrame:
        """Return 10-second aggregated fills for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_10s WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_agg_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """Return aggregated fills for a date (fallback to 1min)."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_1min WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    def get_ticker_exchange_map(
        self, exchanges: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Return {equ_ticker: exchange} from ticker_repository."""
        conn = self._get_read_conn()
        try:
            params: List[str] = []
            where_clauses: List[str] = []
            if exchanges:
                clean = [str(e).strip().upper() for e in exchanges if str(e).strip()]
                if not clean:
                    return {}
                where_clauses.append(
                    f"UPPER(exchange) IN ({','.join(['?'] * len(clean))})"
                )
                params.extend(clean)
            query = "SELECT equ_ticker, exchange FROM ticker_repository"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)
            rows = conn.execute(query, params).fetchall()
            return {
                str(t): str(e).upper()
                for t, e in rows
                if t is not None and e is not None and str(e).strip()
            }
        finally:
            conn.close()

    def get_order_labels(self) -> pd.DataFrame:
        """Return order labels."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM order_label", conn.raw_connection,
            )
        finally:
            conn.close()
