"""
Schema initialization for processed_fills.db.

Defers base DDL to ``DataPipeline.storage.schema.inline_ddl`` (single source
of truth) and applies production‑only extras: PK migration, column backfill,
data migration, and legacy view creation.

Callers use :func:`init_processed_fills_schema` once at startup with any
``BaseRepository`` that targets ``database="processed_fills"``.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, List

from DataPipeline.config import Config
from DataPipeline.storage.schema.columns import (
    COLUMN_TYPE_MAP,
    PROCESSED_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)
from DataPipeline.storage.schema.inline_ddl import init_processed_fills_schema as _init_base_ddl

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
        _init_base_ddl(conn)

        _migrate_processed_fills_pk(conn)

        _backfill_missing_processed_columns(conn, repo)
        _backfill_missing_route_registry_columns(conn, repo)
        _backfill_exchange(conn)
        _create_legacy_view(conn)

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


def _backfill_missing_processed_columns(conn: sqlite3.Connection, repo: BaseRepository) -> None:
    """Add any missing columns to processed_fills table."""
    proc_info = conn.execute(f"PRAGMA table_info({Config.PROCESSED_FILLS_TABLE})").fetchall()
    proc_existing_cols = {row[1] for row in proc_info}
    for col in PROCESSED_COLUMNS:
        if col not in proc_existing_cols:
            col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
            conn.execute(f"ALTER TABLE {Config.PROCESSED_FILLS_TABLE} ADD COLUMN [{col}] {col_type}")


def _backfill_missing_route_registry_columns(conn: sqlite3.Connection, repo: BaseRepository) -> None:
    """Add any missing columns to route_registry table."""
    route_info = conn.execute("PRAGMA table_info(route_registry)").fetchall()
    route_existing_cols = {row[1] for row in route_info}
    for col in ROUTE_REGISTRY_COLUMNS:
        if col not in route_existing_cols:
            col_type = COLUMN_TYPE_MAP.get(col, "TEXT")
            conn.execute(f"ALTER TABLE route_registry ADD COLUMN [{col}] {col_type}")


def _backfill_exchange(conn: sqlite3.Connection) -> None:
    """Backfill processed_fills.Exchange from route_registry for legacy rows."""
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


def _create_legacy_view(conn: sqlite3.Connection) -> None:
    """Create v_processed_fills_legacy compatibility view."""
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
