"""
Ticker metadata repository.

Manages four tables that track ticker-related metadata:

- ``ticker_date_mapping`` — equ_ticker/ccy_ticker → order_as_of_date index
- ``ticker_repository`` — equ_ticker → exchange mapping (for BDIB fetch)
- ``equ_ticker_registry`` — downstream summary: first/last seen date, order count
- ``ccy_ticker_registry`` — downstream summary: first/last seen date, order count
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Dict, List, Optional

import pandas as pd

from ..processing_config import ProcessingConfig as Config
from ._base import BaseProcessedFillsRepo

logger = logging.getLogger(__name__)


class TickerRepository(BaseProcessedFillsRepo):
    """Repository for ticker metadata (date mapping, exchange mapping, registries)."""

    # ── Ticker-Date Mapping ────────────────────────────────────────────

    def update_ticker_date_mapping(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Update ticker→date mapping from processed fills DataFrame.

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        if df.empty:
            return

        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            records = []

            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                for ticker, dates in df.groupby("equ_ticker")["order_as_of_date"].apply(set).items():
                    for date_str in dates:
                        if ticker and date_str:
                            records.append((str(ticker), "equ_ticker", str(date_str)))

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
                if own_conn:
                    conn.commit()
                logger.debug(f"Updated ticker-date mapping: {len(records)} entries")
        finally:
            if own_conn:
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

    # ── Ticker Repository (equ_ticker → Exchange) ─────────────────────

    def update_ticker_repository(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Upsert equ_ticker → Exchange mapping from aggregated fills."""
        if df.empty or "equ_ticker" not in df.columns or "Exchange" not in df.columns:
            return

        work = df[["equ_ticker", "Exchange"]].dropna().copy()
        if work.empty:
            return

        work["equ_ticker"] = work["equ_ticker"].astype(str).str.strip()
        work["Exchange"] = work["Exchange"].astype(str).str.strip().str.upper()
        work = work[
            work["equ_ticker"].ne("")
            & work["equ_ticker"].str.lower().ne("none")
            & work["equ_ticker"].str.lower().ne("nan")
            & work["Exchange"].ne("")
            & work["Exchange"].str.lower().ne("none")
            & work["Exchange"].str.lower().ne("nan")
        ]
        if work.empty:
            return

        pairs = list(
            work.drop_duplicates(subset=["equ_ticker"])[["equ_ticker", "Exchange"]].itertuples(
                index=False, name=None
            )
        )

        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            conn.executemany(
                """
                INSERT INTO ticker_repository (equ_ticker, exchange, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(equ_ticker) DO UPDATE SET
                    exchange = excluded.exchange,
                    updated_at = datetime('now')
                """,
                pairs,
            )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    def get_ticker_exchange_map(
        self,
        tickers: Optional[List[str]] = None,
        exchanges: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Get equ_ticker → Exchange mapping from ticker_repository."""
        conn = self._get_conn()
        try:
            params: List[str] = []
            where_clauses: List[str] = []

            if tickers:
                clean_tickers = [str(t).strip() for t in tickers if str(t).strip()]
                if not clean_tickers:
                    return {}
                where_clauses.append(f"equ_ticker IN ({','.join(['?'] * len(clean_tickers))})")
                params.extend(clean_tickers)

            if exchanges:
                clean_exchanges = [
                    str(e).strip().upper() for e in exchanges if str(e).strip()
                ]
                if not clean_exchanges:
                    return {}
                where_clauses.append(
                    f"UPPER(exchange) IN ({','.join(['?'] * len(clean_exchanges))})"
                )
                params.extend(clean_exchanges)

            query = "SELECT equ_ticker, exchange FROM ticker_repository"
            if where_clauses:
                query += " WHERE " + " AND ".join(where_clauses)

            rows = conn.execute(query, params).fetchall()

            return {
                str(ticker): str(exchange).upper()
                for ticker, exchange in rows
                if ticker is not None and exchange is not None and str(exchange).strip()
            }
        finally:
            conn.close()

    # ── Ticker Registries (Phase 4A) ──────────────────────────────────

    def update_ticker_registries(
        self,
        df: pd.DataFrame,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        """Update ``equ_ticker_registry`` and ``ccy_ticker_registry`` from processed fills.

        Computes ``first_seen_date``, ``last_seen_date``, and ``order_count``
        per ticker.  Uses ``INSERT OR REPLACE`` with ``MIN/MAX`` logic for
        date tracking.

        If ``conn`` is provided, uses it without commit/close
        (caller manages transaction).
        """
        if df.empty:
            return

        own_conn = conn is None
        if own_conn:
            conn = self._get_admin_conn()
        try:
            # Equity ticker registry
            if "equ_ticker" in df.columns and "order_as_of_date" in df.columns:
                equ_groups = (
                    df.groupby("equ_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )

                for _, row in equ_groups.iterrows():
                    ticker = str(row["equ_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"""INSERT INTO {Config.EQU_TICKER_REGISTRY_TABLE}
                            (equ_ticker, first_seen_date, last_seen_date, order_count)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(equ_ticker) DO UPDATE SET
                                first_seen_date = MIN(first_seen_date, excluded.first_seen_date),
                                last_seen_date = MAX(last_seen_date, excluded.last_seen_date),
                                order_count = order_count + excluded.order_count""",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )

            # Currency ticker registry
            if "ccy_ticker" in df.columns and "order_as_of_date" in df.columns:
                ccy_groups = (
                    df.groupby("ccy_ticker")
                    .agg(
                        first_date=("order_as_of_date", "min"),
                        last_date=("order_as_of_date", "max"),
                        order_count=("OrderId", "nunique"),
                    )
                    .reset_index()
                )

                for _, row in ccy_groups.iterrows():
                    ticker = str(row["ccy_ticker"])
                    if not ticker:
                        continue
                    conn.execute(
                        f"""INSERT INTO {Config.CCY_TICKER_REGISTRY_TABLE}
                            (ccy_ticker, first_seen_date, last_seen_date, order_count)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(ccy_ticker) DO UPDATE SET
                                first_seen_date = MIN(first_seen_date, excluded.first_seen_date),
                                last_seen_date = MAX(last_seen_date, excluded.last_seen_date),
                                order_count = order_count + excluded.order_count""",
                        (ticker, str(row["first_date"]), str(row["last_date"]), int(row["order_count"])),
                    )

            if own_conn:
                conn.commit()
            logger.debug("Updated ticker registries")
        finally:
            if own_conn:
                conn.close()

    def get_equ_ticker_registry(self) -> pd.DataFrame:
        """Get all equity tickers from the registry."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.EQU_TICKER_REGISTRY_TABLE} ORDER BY equ_ticker",
                conn,
            )
        finally:
            conn.close()

    def get_ccy_ticker_registry(self) -> pd.DataFrame:
        """Get all currency tickers from the registry."""
        conn = self._get_conn()
        try:
            return pd.read_sql_query(
                f"SELECT * FROM {Config.CCY_TICKER_REGISTRY_TABLE} ORDER BY ccy_ticker",
                conn,
            )
        finally:
            conn.close()