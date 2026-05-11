"""Fill read repository — read access to processed_fills.db."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
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

    # ── Ticker registry (migrated from ProcessedFillsDB) ──────────────────────

    def get_equ_ticker_registry(self) -> pd.DataFrame:
        """Get all equity tickers from the registry."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM equ_ticker_registry ORDER BY equ_ticker",
                conn.raw_connection,
            )
        finally:
            conn.close()

    def get_ccy_ticker_registry(self) -> pd.DataFrame:
        """Get all currency tickers from the registry."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM ccy_ticker_registry ORDER BY ccy_ticker",
                conn.raw_connection,
            )
        finally:
            conn.close()

    def get_ticker_dates(
        self, ticker_type: str = "equ_ticker",
    ) -> Dict[str, List[str]]:
        """Get ticker→dates mapping from ticker_date_mapping table."""
        conn = self._get_read_conn()
        try:
            cur = conn.execute(
                "SELECT ticker, order_as_of_date FROM ticker_date_mapping "
                "WHERE ticker_type = ? ORDER BY ticker, order_as_of_date",
                (ticker_type,),
            )
            result: Dict[str, List[str]] = {}
            for ticker, date_str in cur.fetchall():
                result.setdefault(ticker, []).append(date_str)
            return result
        finally:
            conn.close()

    # ── Range queries (migrated from ProcessedFillsRepository) ──────────────

    def get_processed_fills_for_date_range(
        self, start: str, end: str,
    ) -> pd.DataFrame:
        """Get processed fills for a date range (inclusive, YYYYMMDD)."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                """SELECT * FROM processed_fills
                    WHERE order_as_of_date >= ? AND order_as_of_date <= ?
                    ORDER BY order_as_of_date, mkt_timestamp""",
                conn.raw_connection,
                params=[start, end],
            )
        finally:
            conn.close()

    # ── Order labels by date (migrated from OrderLabelRepository) ──────────

    def get_order_labels_for_date(self, date_str: str) -> pd.DataFrame:
        """Get order labels for a specific date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM order_label WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Execution history stats (migrated from ExecutionHistoryRepository) ──

    def get_execution_history_stats(self) -> Dict[str, Any]:
        """Return row counts and source policy metadata for execution history tables."""
        conn = self._get_read_conn()
        try:
            return {
                "order_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM order_history"
                ).fetchone()[0],
                "route_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM route_history"
                ).fetchone()[0],
                "route_event_history_rows": conn.execute(
                    "SELECT COUNT(*) FROM route_event_history"
                ).fetchone()[0],
                "source_policy": dict(Config.EXECUTION_HISTORY_SOURCE_POLICY),
                "refresh_policy": dict(Config.EXECUTION_HISTORY_REFRESH_POLICY),
            }
        finally:
            conn.close()

    # ── 1-minute aggregation reads (migrated from AggregationRepository) ────

    def get_agg_fills_1min_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED v3] Get route-level 1min aggregated fills for a date."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM agg_fills_1min WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Legacy reads (migrated from LegacyRepository) ──────────────────────

    def get_1min_fills_for_date(self, date_str: str) -> pd.DataFrame:
        """[DEPRECATED] Legacy: get 1min aggregated fills for a date from old table."""
        conn = self._get_read_conn()
        try:
            return pd.read_sql_query(
                "SELECT * FROM processed_fills_1min WHERE order_as_of_date = ?",
                conn.raw_connection,
                params=[date_str],
            )
        finally:
            conn.close()

    # ── Cross-table stats (migrated from processed_fills_db.stats) ─────────

    def get_processing_stats(self) -> Dict[str, Any]:
        """Get summary statistics across all tables in processed_fills.db."""
        conn = self._get_read_conn()
        try:
            stats: Dict[str, Any] = {}
            for table in [
                Config.PROCESSED_FILLS_TABLE,
                Config.AGG_10S_TABLE,
                Config.AGG_1MIN_TABLE,
                Config.ORDER_HISTORY_TABLE,
                Config.ROUTE_HISTORY_TABLE,
                Config.ROUTE_EVENT_HISTORY_TABLE,
                Config.AGG_PROCESSED_FILLS_TABLE,
                Config.PROCESSED_FILLS_1MIN_TABLE,
                Config.ORDER_LABEL_TABLE,
            ]:
                try:
                    cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    stats[table] = cursor.fetchone()[0]
                except Exception:
                    stats[table] = 0

            try:
                cursor = conn.execute(
                    f"SELECT stage, COUNT(DISTINCT order_as_of_date) "
                    f"FROM {Config.PROCESSING_LOG_TABLE} GROUP BY stage"
                )
                stats["processing_stages"] = {r[0]: r[1] for r in cursor.fetchall()}
            except Exception:
                stats["processing_stages"] = {}

            return stats
        finally:
            conn.close()
