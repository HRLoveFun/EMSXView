-- ============================================================================
-- processed_fills.db Vertical Partition — execution_history.db / ticker_registry.db
-- ============================================================================
-- Splits the 15-table processed_fills.db into 3 databases by access pattern:
--   processed_fills.db  — high-write (processed_fills, agg_fills_10s/1min, processing_log)
--   execution_history.db — read-heavy archival (route_registry, order_history,
--                          route_history, route_event_history)
--   ticker_registry.db   — read-only reference (ticker_repository, equ_ticker_registry,
--                          ccy_ticker_registry, ticker_date_mapping, order_label)
-- ============================================================================

-- ------------------------------------------------------------------
-- execution_history.db — Read-heavy archival tables
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS route_registry (
    OrderId TEXT NOT NULL,
    RouteId TEXT NOT NULL,
    EquTicker TEXT,
    Exchange TEXT,
    Broker TEXT,
    Algo TEXT,
    Side TEXT,
    Currency TEXT,
    Amount REAL,
    total_fills INTEGER,
    source_lineage TEXT DEFAULT 'emsx.history:GetFills',
    source_priority TEXT DEFAULT 'primary',
    refreshed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (OrderId, RouteId)
);

CREATE TABLE IF NOT EXISTS order_history (
    OrderId TEXT NOT NULL,
    order_as_of_date TEXT NOT NULL,
    EquTicker TEXT,
    Exchange TEXT,
    Broker TEXT,
    Algo TEXT,
    StrategyType TEXT,
    Side TEXT,
    Currency TEXT,
    Amount REAL,
    OrderPrice REAL,
    FillPct REAL,
    TotalVolume REAL,
    AvgPrice REAL,
    fill_count INTEGER,
    route_count INTEGER,
    source_lineage TEXT DEFAULT 'costview.fill-rollup',
    source_priority TEXT DEFAULT 'primary',
    refresh_strategy TEXT DEFAULT 'rebuild-per-processed-date',
    refreshed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (OrderId, order_as_of_date)
);

CREATE TABLE IF NOT EXISTS route_history (
    OrderId TEXT NOT NULL,
    RouteId TEXT NOT NULL,
    order_as_of_date TEXT NOT NULL,
    EquTicker TEXT,
    Exchange TEXT,
    Broker TEXT,
    Algo TEXT,
    Side TEXT,
    Currency TEXT,
    Amount REAL,
    exec_price REAL,
    exec_volume REAL,
    fill_count INTEGER,
    source_lineage TEXT DEFAULT 'costview.fill-rollup',
    source_priority TEXT DEFAULT 'primary',
    refresh_strategy TEXT DEFAULT 'rebuild-per-processed-date',
    refreshed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (OrderId, RouteId, order_as_of_date)
);

CREATE TABLE IF NOT EXISTS route_event_history (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderId TEXT NOT NULL,
    RouteId TEXT NOT NULL,
    order_as_of_date TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    event_type TEXT DEFAULT 'fill',
    EquTicker TEXT,
    FillPrice REAL,
    FillShares REAL,
    ExecType TEXT,
    source_lineage TEXT DEFAULT 'emsx.history:GetFills',
    source_priority TEXT DEFAULT 'primary',
    refresh_strategy TEXT DEFAULT 'append-per-fill',
    refreshed_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for execution_history.db

CREATE INDEX IF NOT EXISTS idx_order_history_date
    ON order_history(order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_order_history_ticker
    ON order_history(EquTicker);
CREATE INDEX IF NOT EXISTS idx_order_history_date_order_cover
    ON order_history(order_as_of_date, OrderId, EquTicker, Algo, Broker,
                     FillPct, TotalVolume, AvgPrice);

CREATE INDEX IF NOT EXISTS idx_route_history_date
    ON route_history(order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_route_history_ticker
    ON route_history(EquTicker);

CREATE INDEX IF NOT EXISTS idx_route_event_history_date
    ON route_event_history(order_as_of_date);
CREATE INDEX IF NOT EXISTS idx_route_event_history_route
    ON route_event_history(OrderId, RouteId);
CREATE INDEX IF NOT EXISTS idx_route_event_history_timestamp
    ON route_event_history(event_timestamp);
CREATE INDEX IF NOT EXISTS idx_route_event_route_ts_type
    ON route_event_history(OrderId, RouteId, event_timestamp, event_type);
CREATE INDEX IF NOT EXISTS idx_route_event_order_date
    ON route_event_history(OrderId, order_as_of_date);

-- ------------------------------------------------------------------
-- ticker_registry.db — Read-only reference tables
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ticker_repository (
    equ_ticker TEXT PRIMARY KEY,
    Exchange TEXT,
    market_code TEXT,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS equ_ticker_registry (
    equ_ticker TEXT PRIMARY KEY,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ccy_ticker_registry (
    ccy_ticker TEXT PRIMARY KEY,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ticker_date_mapping (
    ticker TEXT NOT NULL,
    ticker_type TEXT NOT NULL,
    order_as_of_date TEXT NOT NULL,
    PRIMARY KEY (ticker, ticker_type, order_as_of_date)
);

CREATE TABLE IF NOT EXISTS order_label (
    OrderId TEXT PRIMARY KEY,
    Broker TEXT,
    Algo TEXT,
    EquTicker TEXT,
    Side TEXT,
    label_date TEXT DEFAULT (date('now'))
);

-- ------------------------------------------------------------------
-- processed_fills.db — Retained tables (high-write, compact)
-- ------------------------------------------------------------------

-- NOTE: These tables should be REMOVED from processed_fills.db DDL
-- after data migration.  Kept in inline DDL temporarily for
-- backward compatibility.  Run the VACUUM after migration.

-- Tables RETAINED in processed_fills.db:
--   processed_fills        (core fill data)
--   agg_fills_10s          (10-second VWAP aggregation)
--   agg_fills_1min         (1-minute aggregation, deprecated)
--   agg_processed_fills    (legacy order-level agg)
--   processed_fills_1min   (legacy 1min agg)
--   processing_log         (pipeline stage audit)

-- Tables MOVED to execution_history.db:
--   route_registry
--   order_history
--   route_history
--   route_event_history

-- Tables MOVED to ticker_registry.db:
--   ticker_repository
--   equ_ticker_registry
--   ccy_ticker_registry
--   ticker_date_mapping
--   order_label
