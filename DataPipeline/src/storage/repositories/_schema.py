"""
Schema initialization for processed_fills.db.

Schema creation is coordinated here — not scattered across 6 files —
because the 15+ tables have interdependencies (views, FK-style joins,
migration order).

Callers use :func:`init_processed_fills_schema` once at startup. Any
``BaseRepository`` subclass that targets ``database="processed_fills"``
suffices — this function only calls ``_get_admin_conn()`` and
``_build_column_defs()``.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, List

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from DataPipeline.src.storage.schema.columns import (
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    COLUMN_TYPE_MAP,
    ORDER_HISTORY_COLUMNS,
    PROCESSED_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)

if TYPE_CHECKING:
    from ._base import BaseRepository

logger = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────


def init_processed_fills_schema(repo: BaseRepository) -> None:
    """Initialize ALL tables in processed_fills.db (idempotent).

    Parameters
    ----------
    repo : BaseRepository
        Any ``BaseRepository`` targeting ``"processed_fills"`` — only used
        for ``_get_admin_conn()`` and ``_build_column_defs()``.
    """
    conn = repo._get_admin_conn()
    try:
        # -- processed_fills: Fact table (Schema V2) --
        proc_cols = repo._build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
                {proc_cols},
                PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
            )
        """)

        _migrate_processed_fills_pk(conn)

        proc_info = conn.execute(f"PRAGMA table_info({Config.PROCESSED_FILLS_TABLE})").fetchall()
        proc_existing_cols = {row[1] for row in proc_info}
        for col in PROCESSED_COLUMNS:
            if col not in proc_existing_cols:
                col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
                conn.execute(f"ALTER TABLE {Config.PROCESSED_FILLS_TABLE} ADD COLUMN [{col}] {col_type}")

        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_proc_date
            ON {Config.PROCESSED_FILLS_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_proc_orderid
            ON {Config.PROCESSED_FILLS_TABLE} (OrderId)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_proc_routeid
            ON {Config.PROCESSED_FILLS_TABLE} (RouteId)
        """)

        # -- route_registry --
        route_reg_cols = repo._build_column_defs(ROUTE_REGISTRY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS route_registry (
                {route_reg_cols},
                PRIMARY KEY (OrderId, RouteId)
            )
        """)

        # Order history
        order_history_cols = repo._build_column_defs(ORDER_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ORDER_HISTORY_TABLE} (
                {order_history_cols},
                PRIMARY KEY (OrderId, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_order_history_date
            ON {Config.ORDER_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_order_history_ticker
            ON {Config.ORDER_HISTORY_TABLE} (equ_ticker)
        """)

        # Route history
        route_history_cols = repo._build_column_defs(ROUTE_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ROUTE_HISTORY_TABLE} (
                {route_history_cols},
                PRIMARY KEY (OrderId, RouteId, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_history_date
            ON {Config.ROUTE_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_history_ticker
            ON {Config.ROUTE_HISTORY_TABLE} (equ_ticker)
        """)

        # Route event history
        route_event_history_cols = repo._build_column_defs(ROUTE_EVENT_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ROUTE_EVENT_HISTORY_TABLE} (
                {route_event_history_cols},
                PRIMARY KEY (event_id)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_date
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (order_as_of_date)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_route
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (OrderId, RouteId)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_route_event_history_timestamp
            ON {Config.ROUTE_EVENT_HISTORY_TABLE} (event_timestamp)
        """)

        # Route registry schema migration: add missing columns
        route_info = conn.execute("PRAGMA table_info(route_registry)").fetchall()
        route_existing_cols = {row[1] for row in route_info}
        for col in ROUTE_REGISTRY_COLUMNS:
            if col not in route_existing_cols:
                col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
                conn.execute(f"ALTER TABLE route_registry ADD COLUMN [{col}] {col_type}")

        # Backfill processed_fills.Exchange from route_registry for legacy rows.
        conn.execute(f"""
            UPDATE {Config.PROCESSED_FILLS_TABLE}
            SET Exchange = (
                SELECT r.Exchange
                FROM route_registry r
                WHERE r.OrderId = {Config.PROCESSED_FILLS_TABLE}.OrderId
                  AND r.RouteId = {Config.PROCESSED_FILLS_TABLE}.RouteId
            )
            WHERE Exchange IS NULL OR TRIM(Exchange) = ''
        """)

        # -- v_processed_fills_legacy: Compatibility view --
        conn.execute(f"""
            CREATE VIEW IF NOT EXISTS v_processed_fills_legacy AS
            SELECT 
                r.OrderId,
                p.FillId,
                p.order_as_of_date,
                p.mkt_timestamp,
                p.exchange_exec_time,
                CASE
                    WHEN r.equ_ticker IS NULL OR TRIM(r.equ_ticker) = '' THEN NULL
                    WHEN INSTR(TRIM(r.equ_ticker), ' ') > 0 THEN SUBSTR(TRIM(r.equ_ticker), 1, INSTR(TRIM(r.equ_ticker), ' ') - 1)
                    ELSE TRIM(r.equ_ticker)
                END AS Ticker,
                r.equ_ticker,
                CASE
                    WHEN p.Exchange IS NULL OR TRIM(p.Exchange) = '' THEN NULL
                    WHEN LOWER(TRIM(p.Exchange)) IN ('none', 'nan') THEN NULL
                    ELSE UPPER(TRIM(p.Exchange))
                END AS Exchange,
                p.Amount,
                r.Side,
                CASE
                    WHEN r.ccy_ticker IS NULL OR TRIM(r.ccy_ticker) = '' THEN NULL
                    WHEN INSTR(TRIM(r.ccy_ticker), ' ') > 0 THEN SUBSTR(TRIM(r.ccy_ticker), 1, INSTR(TRIM(r.ccy_ticker), ' ') - 1)
                    ELSE SUBSTR(TRIM(r.ccy_ticker), 1, 3)
                END AS Currency,
                p.region,
                p.Broker,
                p.StrategyType,
                p.algo,
                r.ccy_ticker,
                p.is_closing_auction,
                p.route_as_of_time,
                p.RouteShares,
                p.TraderName,
                p.FillPrice,
                p.FillShares,
                p.ExecType,
                r.RouteId,
                p.DateTimeOfFill
            FROM {Config.PROCESSED_FILLS_TABLE} p
            LEFT JOIN route_registry r ON p.OrderId = r.OrderId AND p.RouteId = r.RouteId
        """)

        # -- agg_fills_10s: route-level 10s aggregation --
        agg_cols = repo._build_column_defs(AGG_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.AGG_10S_TABLE} (
                {agg_cols},
                PRIMARY KEY (OrderId, RouteId, mkt_timestamp, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_agg_10s_order_route
            ON {Config.AGG_10S_TABLE} (OrderId, RouteId)
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_agg_10s_date
            ON {Config.AGG_10S_TABLE} (order_as_of_date)
        """)

        # -- agg_fills_1min: route-level 1min aggregation --
        agg_1min_cols = repo._build_column_defs(AGG_1MIN_COLUMNS, COLUMN_TYPE_MAP)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.AGG_1MIN_TABLE} (
                {agg_1min_cols},
                PRIMARY KEY (OrderId, RouteId, mkt_timestamp_1min, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_agg_1min_date
            ON {Config.AGG_1MIN_TABLE} (order_as_of_date)
        """)

        # -- processing_log --
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

        # -- ticker_date_mapping --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.TICKER_DATE_MAPPING_TABLE} (
                ticker TEXT NOT NULL,
                ticker_type TEXT NOT NULL,
                order_as_of_date TEXT NOT NULL,
                PRIMARY KEY (ticker, ticker_type, order_as_of_date)
            )
        """)

        # -- order_label --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.ORDER_LABEL_TABLE} (
                OrderId TEXT PRIMARY KEY,
                order_as_of_date TEXT
            )
        """)

        # -- ticker_repository --
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticker_repository (
                equ_ticker TEXT PRIMARY KEY,
                exchange   TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # -- equ_ticker_registry --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.EQU_TICKER_REGISTRY_TABLE} (
                equ_ticker      TEXT PRIMARY KEY,
                first_seen_date TEXT,
                last_seen_date  TEXT,
                order_count     INTEGER DEFAULT 0
            )
        """)

        # -- ccy_ticker_registry --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.CCY_TICKER_REGISTRY_TABLE} (
                ccy_ticker      TEXT PRIMARY KEY,
                first_seen_date TEXT,
                last_seen_date  TEXT,
                order_count     INTEGER DEFAULT 0
            )
        """)

        # -- Legacy tables --
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.AGG_PROCESSED_FILLS_TABLE} (
                OrderId TEXT NOT NULL,
                mkt_timestamp TEXT NOT NULL,
                order_as_of_date TEXT,
                PRIMARY KEY (OrderId, mkt_timestamp, order_as_of_date)
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_1MIN_TABLE} (
                OrderId TEXT NOT NULL,
                mkt_timestamp_1min TEXT NOT NULL,
                order_as_of_date TEXT,
                PRIMARY KEY (OrderId, mkt_timestamp_1min, order_as_of_date)
            )
        """)

        conn.commit()
        logger.debug("Processed fills DB schema initialized")
    finally:
        conn.close()


# ── Internal helpers ──────────────────────────────────────────────────────


def _migrate_processed_fills_pk(conn: sqlite3.Connection) -> None:
    """Upgrade processed_fills PK to composite key if needed."""
    cursor = conn.execute(f"PRAGMA table_info({Config.PROCESSED_FILLS_TABLE})")
    col_info = cursor.fetchall()
    if not col_info:
        return

    pk_cols = [row[5] for row in col_info if row[5] > 0]
    if pk_cols == [1]:
        logger.info("Migrating processed_fills PK from single FillId to composite (OrderId, RouteId, FillId, order_as_of_date)")
        conn.execute(f"""
            CREATE TABLE {Config.PROCESSED_FILLS_TABLE}_new (
                {', '.join(f'[{row[1]}] {row[2]}' + (' PRIMARY KEY' if row[5] > 0 else '') for row in col_info)},
                PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
            )
        """)
        conn.execute(f"""
            INSERT INTO {Config.PROCESSED_FILLS_TABLE}_new
            SELECT DISTINCT * FROM {Config.PROCESSED_FILLS_TABLE}
        """)
        conn.execute(f"DROP TABLE {Config.PROCESSED_FILLS_TABLE}")
        conn.execute(f"ALTER TABLE {Config.PROCESSED_FILLS_TABLE}_new RENAME TO {Config.PROCESSED_FILLS_TABLE}")
        logger.info("Processed fills PK migration complete")
