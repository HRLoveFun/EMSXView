"""Inline DDL for databases without formal migration systems.

Each function creates tables and indexes (IF NOT EXISTS) for a specific
database, using a raw ``sqlite3.Connection`` obtained from
``ConnectionManager.get_admin_connection()``.

These functions are called by ``MigrationManager._ensure_inline_schema()``
instead of instantiating old DB classes, breaking the dependency on the
legacy layer.

Note: migration logic (ALTER TABLE ADD COLUMN) is intentionally omitted
here.  That logic is idempotent and runs automatically when the old DB
classes are instantiated by the pipeline.  The purpose of this module is
to ensure the database file and its base schema exist.
"""

from __future__ import annotations

import logging
import sqlite3

from DataPipeline.config import Config
from .columns import (
    AGG_1MIN_COLUMNS,
    AGG_COLUMNS,
    COLUMN_TYPE_MAP,
    ORDER_HISTORY_COLUMNS,
    PROCESSED_COLUMNS,
    ROUTE_EVENT_HISTORY_COLUMNS,
    ROUTE_HISTORY_COLUMNS,
    ROUTE_REGISTRY_COLUMNS,
)

logger = logging.getLogger(__name__)


def _build_column_defs(columns: list[str], type_map: dict[str, str]) -> str:
    """Build SQL column definition string from column list."""
    parts = []
    for col in columns:
        col_type = type_map.get(col, "TEXT")
        parts.append(f"[{col}] {col_type}")
    return ",\n                    ".join(parts)


def init_raw_fills_schema(conn: sqlite3.Connection) -> None:
    """Create raw_fills.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.RAW_FILLS_TABLE} (
            OrderId               TEXT NOT NULL,
            Account               TEXT,
            SecurityName          TEXT,
            Ticker                TEXT,
            Exchange              TEXT,
            Currency              TEXT,
            Side                  TEXT,
            Amount                TEXT,
            NyOrderCreateAsOfDateTime TEXT,
            Type                  TEXT,
            LimitPrice            TEXT,
            Broker                TEXT,
            StopPrice             TEXT,
            StrategyType          TEXT,
            TraderName            TEXT,
            TraderUuid            TEXT,
            RouteId               TEXT NOT NULL,
            NyTranCreateAsOfDateTime TEXT,
            RouteShares           TEXT,
            FillId                TEXT NOT NULL,
            ExecType              TEXT,
            DateTimeOfFill        TEXT,
            FillPrice             TEXT,
            FillShares            TEXT,
            LastCapacity          TEXT,
            LastMarket            TEXT,
            Liquidity             TEXT,
            LocalExchangeSymbol   TEXT,
            source_date           TEXT NOT NULL DEFAULT '',
            fetched_at            TEXT DEFAULT (datetime('now')),
            ingested_at           TEXT DEFAULT (datetime('now')),
            order_as_of_date      TEXT DEFAULT '',
            exchange_exec_time    TEXT DEFAULT '',
            PRIMARY KEY (OrderId, RouteId, FillId)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_source_date
        ON {Config.RAW_FILLS_TABLE} (source_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_order_date
        ON {Config.RAW_FILLS_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_raw_ticker
        ON {Config.RAW_FILLS_TABLE} (Ticker)
    """)

    # fetch_log
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.FETCH_LOG_TABLE} (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            source_date           TEXT NOT NULL,
            fetch_timestamp       TEXT DEFAULT (datetime('now')),
            row_count             INTEGER NOT NULL,
            data_hash             TEXT NOT NULL,
            file_path             TEXT,
            status                TEXT DEFAULT 'fetched',
            UNIQUE(source_date, data_hash)
        )
    """)

    # ingestion_log (legacy)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.INGESTION_LOG_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_date TEXT NOT NULL,
            source_file TEXT,
            ingestion_timestamp TEXT DEFAULT (datetime('now')),
            row_count INTEGER,
            new_row_count INTEGER,
            hash_value TEXT,
            UNIQUE(source_date, hash_value)
        )
    """)

    # order_fetch_log
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ORDER_FETCH_LOG_TABLE} (
            order_id              TEXT NOT NULL,
            source_date           TEXT NOT NULL,
            fetch_timestamp       TEXT DEFAULT (datetime('now')),
            row_count             INTEGER NOT NULL,
            data_hash             TEXT NOT NULL,
            PRIMARY KEY (order_id, source_date)
        )
    """)
    conn.commit()
    logger.debug("raw_fills.db schema ensured (inline DDL)")


def init_raw_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create raw_bdib.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.RAW_BDIB_TABLE} (
            equ_ticker       TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            mkt_timestamp    TEXT NOT NULL,
            open             REAL,
            high             REAL,
            low              REAL,
            close            REAL,
            volume           REAL,
            num_trds         REAL,
            value            REAL,
            fetched_at       TEXT DEFAULT (datetime('now')),
            source           TEXT DEFAULT 'bloomberg',
            PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_date ON {Config.RAW_BDIB_TABLE} (order_as_of_date)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_ticker ON {Config.RAW_BDIB_TABLE} (equ_ticker)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_raw_bdib_date_ticker ON {Config.RAW_BDIB_TABLE} (order_as_of_date, equ_ticker)"
    )

    # bdib_daily_summary
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.BDIB_DAILY_SUMMARY_TABLE} (
            equ_ticker        TEXT NOT NULL,
            trade_date        TEXT NOT NULL,
            total_volume      REAL,
            daily_vwap        REAL,
            daily_close       REAL,
            daily_volatility  REAL,
            intraday_volatility REAL,
            adv_5d            REAL,
            adv_20d           REAL,
            computed_at       TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (equ_ticker, trade_date)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_daily_summary_ticker "
        f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (equ_ticker)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_daily_summary_date "
        f"ON {Config.BDIB_DAILY_SUMMARY_TABLE} (trade_date)"
    )
    conn.commit()
    logger.debug("raw_bdib.db schema ensured (inline DDL)")


def init_processed_raw_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create processed_raw_bdib.db tables and indexes."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSED_RAW_BDIB_TABLE} (
            equ_ticker       TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            mkt_timestamp    TEXT NOT NULL,
            open             REAL,
            high             REAL,
            low              REAL,
            close            REAL,
            volume           REAL,
            num_trds         REAL,
            value            REAL,
            vwap             REAL,
            fluctuation      REAL,
            log_chg_pct_10s  REAL,
            fetched_at       TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (equ_ticker, order_as_of_date, mkt_timestamp)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_date ON {Config.PROCESSED_RAW_BDIB_TABLE} (order_as_of_date)"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_ticker ON {Config.PROCESSED_RAW_BDIB_TABLE} (equ_ticker)"
    )
    conn.commit()
    logger.debug("processed_raw_bdib.db schema ensured (inline DDL)")


def init_fill_bdib_schema(conn: sqlite3.Connection) -> None:
    """Create fill_bdib.db tables and indexes."""
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
    logger.debug("fill_bdib.db schema ensured (inline DDL)")


def init_processed_fills_schema(conn: sqlite3.Connection) -> None:
    """Create processed_fills.db tables and indexes.

    This is the most complex database with 7+ tables.  Column definitions
    are imported from ``db.schema.columns`` to stay in sync with the rest
    of the codebase.
    """
    # ── processed_fills ──
    proc_cols = _build_column_defs(PROCESSED_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.PROCESSED_FILLS_TABLE} (
            {proc_cols},
            PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)
        )
    """)
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

    # ── route_registry ──
    route_reg_cols = _build_column_defs(ROUTE_REGISTRY_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS route_registry (
            {route_reg_cols},
            PRIMARY KEY (OrderId, RouteId)
        )
    """)

    # ── order_history ──
    order_history_cols = _build_column_defs(ORDER_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
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

    # ── route_history ──
    route_history_cols = _build_column_defs(ROUTE_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
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

    # ── route_event_history ──
    route_event_history_cols = _build_column_defs(ROUTE_EVENT_HISTORY_COLUMNS, COLUMN_TYPE_MAP)
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

    # ── processing_log ──
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

    # ── ticker_date_mapping ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.TICKER_DATE_MAPPING_TABLE} (
            ticker TEXT NOT NULL,
            ticker_type TEXT NOT NULL,
            order_as_of_date TEXT NOT NULL,
            PRIMARY KEY (ticker, ticker_type, order_as_of_date)
        )
    """)

    # ── order_label ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.ORDER_LABEL_TABLE} (
            OrderId TEXT PRIMARY KEY,
            order_as_of_date TEXT
        )
    """)

    # ── ticker_repository ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticker_repository (
            equ_ticker TEXT PRIMARY KEY,
            exchange   TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── equ_ticker_registry ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.EQU_TICKER_REGISTRY_TABLE} (
            equ_ticker      TEXT PRIMARY KEY,
            first_seen_date TEXT,
            last_seen_date  TEXT,
            order_count     INTEGER DEFAULT 0
        )
    """)

    # ── ccy_ticker_registry ──
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.CCY_TICKER_REGISTRY_TABLE} (
            ccy_ticker      TEXT PRIMARY KEY,
            first_seen_date TEXT,
            last_seen_date  TEXT,
            order_count     INTEGER DEFAULT 0
        )
    """)

    # ── agg_fills_10s ──
    agg_cols = _build_column_defs(AGG_COLUMNS, COLUMN_TYPE_MAP)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {Config.AGG_10S_TABLE} (
            {agg_cols},
            PRIMARY KEY (OrderId, RouteId, mkt_timestamp, order_as_of_date)
        )
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_agg_10s_date
        ON {Config.AGG_10S_TABLE} (order_as_of_date)
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_agg_10s_order_route
        ON {Config.AGG_10S_TABLE} (OrderId, RouteId)
    """)

    # ── agg_fills_1min ──
    agg_1min_cols = _build_column_defs(AGG_1MIN_COLUMNS, COLUMN_TYPE_MAP)
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

    # ── Legacy tables ──
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
    logger.debug("processed_fills.db schema ensured (inline DDL)")
