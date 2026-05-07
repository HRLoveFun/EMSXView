"""
Query CLI Engine — prebuilt queries for convenient CostView data retrieval.

Provides a QueryEngine class with common query patterns against both
raw_fills.db and processed_fills.db, with output formatting support.

Usage (via __main__.py):
    python -m src --query fills --date 20260408
    python -m src --query fills --order-id 12345
    python -m src --query fills --ticker "7203 JP Equity"
    python -m src --query log --last 10
    python -m src --query orders --date 20260408
    python -m src --query tickers
    python -m src --query summary --date 20260408
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

import pandas as pd

from .db.connection import AccessTier
from .processed_fills_db import ProcessedFillsDB
from .processing_config import ProcessingConfig as Config
from .raw_fills_db import RawFillsDB

logger = logging.getLogger(__name__)


class QueryEngine:
    """Prebuilt read-only queries against CostView databases."""

    def __init__(self):
        self.raw_db = RawFillsDB(access_tier=AccessTier.READ)
        self.proc_db = ProcessedFillsDB(access_tier=AccessTier.READ)

    def query_fills(
        self,
        date: Optional[str] = None,
        order_id: Optional[str] = None,
        ticker: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> pd.DataFrame:
        """Query processed fills by date, order ID, or ticker."""
        conn = sqlite3.connect(str(self.proc_db.db_path))
        try:
            conditions = []
            params: list = []

            if date:
                conditions.append("order_as_of_date = ?")
                params.append(date)
            if order_id:
                conditions.append("OrderId = ?")
                params.append(order_id)
            if ticker:
                conditions.append("(equ_ticker = ? OR Ticker = ?)")
                params.extend([ticker, ticker])

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.extend([limit, offset])

            return pd.read_sql_query(
                f"""SELECT * FROM {Config.PROCESSED_FILLS_TABLE}
                    {where}
                    ORDER BY order_as_of_date, mkt_timestamp
                    LIMIT ? OFFSET ?""",
                conn,
                params=params,
            )
        finally:
            conn.close()

    def query_raw_fills(
        self,
        date: Optional[str] = None,
        order_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> pd.DataFrame:
        """Query raw fills by date or order ID."""
        conn = sqlite3.connect(str(self.raw_db.db_path))
        try:
            conditions = []
            params: list = []

            if date:
                conditions.append("(order_as_of_date = ? OR source_date = ?)")
                params.extend([date, date])
            if order_id:
                conditions.append("OrderId = ?")
                params.append(order_id)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            params.extend([limit, offset])

            return pd.read_sql_query(
                f"""SELECT * FROM {Config.RAW_FILLS_TABLE}
                    {where}
                    ORDER BY source_date, DateTimeOfFill
                    LIMIT ? OFFSET ?""",
                conn,
                params=params,
            )
        finally:
            conn.close()

    def query_fetch_log(self, last: int = 10) -> List[Dict[str, Any]]:
        """Get recent fetch log entries."""
        return self.raw_db.get_fetch_log_stats()[:last]

    def query_order_fetch_log(
        self,
        date: Optional[str] = None,
        last: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get order-level fetch log entries."""
        return self.raw_db.get_order_fetch_log(source_date=date, limit=last)

    def query_orders(
        self,
        date: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> pd.DataFrame:
        """Query order labels, optionally filtered by date."""
        if date:
            return self.proc_db.get_order_labels_for_date(date)
        return self.proc_db.get_order_labels()

    def query_tickers(self, ticker_type: str = "all") -> pd.DataFrame:
        """List all tracked tickers from ticker_date_mapping."""
        conn = sqlite3.connect(str(self.proc_db.db_path))
        try:
            if ticker_type == "all":
                return pd.read_sql_query(
                    f"""SELECT ticker, ticker_type,
                               MIN(order_as_of_date) AS first_date,
                               MAX(order_as_of_date) AS last_date,
                               COUNT(*) AS date_count
                        FROM {Config.TICKER_DATE_MAPPING_TABLE}
                        GROUP BY ticker, ticker_type
                        ORDER BY ticker_type, ticker""",
                    conn,
                )
            else:
                return pd.read_sql_query(
                    f"""SELECT ticker,
                               MIN(order_as_of_date) AS first_date,
                               MAX(order_as_of_date) AS last_date,
                               COUNT(*) AS date_count
                        FROM {Config.TICKER_DATE_MAPPING_TABLE}
                        WHERE ticker_type = ?
                        GROUP BY ticker
                        ORDER BY ticker""",
                    conn,
                    params=[ticker_type],
                )
        finally:
            conn.close()

    def query_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get pipeline status summary for a date or overall."""
        summary: Dict[str, Any] = {}

        # Raw fills stats
        raw_counts = self.raw_db.get_date_row_counts()
        if date:
            summary["raw_fills"] = raw_counts.get(date, 0)
        else:
            summary["raw_fills_total"] = sum(raw_counts.values())
            summary["raw_fills_dates"] = len(raw_counts)

        # Processing stats
        proc_stats = self.proc_db.get_processing_stats()
        summary["processed_fills"] = proc_stats.get(Config.PROCESSED_FILLS_TABLE, 0)
        summary["agg_fills_10s"] = proc_stats.get(Config.AGG_10S_TABLE, 0)
        summary["order_labels"] = proc_stats.get(Config.ORDER_LABEL_TABLE, 0)
        summary["processing_stages"] = proc_stats.get("processing_stages", {})

        # Ticker counts
        conn = sqlite3.connect(str(self.proc_db.db_path))
        try:
            for tt in ("equ_ticker", "ccy_ticker"):
                try:
                    cursor = conn.execute(
                        f"""SELECT COUNT(DISTINCT ticker) FROM {Config.TICKER_DATE_MAPPING_TABLE}
                            WHERE ticker_type = ?""",
                        (tt,),
                    )
                    summary[f"{tt}_count"] = cursor.fetchone()[0]
                except sqlite3.OperationalError:
                    summary[f"{tt}_count"] = 0
        finally:
            conn.close()

        return summary


def format_output(data, fmt: str = "table") -> str:
    """Format query results for display.

    Args:
        data: DataFrame, list of dicts, or dict.
        fmt: Output format — 'table', 'csv', or 'json'.
    """
    if isinstance(data, pd.DataFrame):
        if data.empty:
            return "(no results)"
        if fmt == "json":
            return data.to_json(orient="records", indent=2, default_handler=str)
        elif fmt == "csv":
            return data.to_csv(index=False)
        else:
            try:
                from tabulate import tabulate
                return tabulate(data, headers="keys", tablefmt="simple", showindex=False)
            except ImportError:
                return data.to_string(index=False)

    elif isinstance(data, list):
        if not data:
            return "(no results)"
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        elif fmt == "csv":
            if isinstance(data[0], dict):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                return output.getvalue()
            return str(data)
        else:
            try:
                from tabulate import tabulate
                return tabulate(data, headers="keys", tablefmt="simple")
            except ImportError:
                return "\n".join(str(row) for row in data)

    elif isinstance(data, dict):
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        else:
            lines = []
            for k, v in data.items():
                lines.append(f"  {k}: {v}")
            return "\n".join(lines)

    return str(data)
