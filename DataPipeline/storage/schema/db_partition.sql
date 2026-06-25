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

-- order_history 是 route_history 在 order 维度的派生视图（PR-1 方案 A 过渡版）
-- ⚠️ 此为 VIEW，不是物理表。任何 INSERT/UPDATE/DELETE 操作将失败。
-- 写入路径：仅需写 route_history，order_history 自动由 SQLite 实时派生。
-- 消费方：tca_query_builder.get_matching_routes / get_order_fill_stats 保持不变。
CREATE VIEW IF NOT EXISTS order_history AS
    SELECT
        OrderId,
        order_as_of_date,
        MAX(equ_ticker)                       AS equ_ticker,
        MAX(ccy_ticker)                       AS ccy_ticker,
        MAX(Side)                             AS Side,
        MAX(Broker)                           AS Broker,
        MAX(algo)                             AS algo,
        MAX(TraderName)                       AS TraderName,
        MAX(Exchange)                         AS Exchange,
        COUNT(DISTINCT RouteId)               AS route_count,
        SUM(fill_count)                       AS fill_count,
        SUM(total_fill_shares)                AS total_fill_shares,
        MAX(order_amount)                     AS order_amount,
        CASE
            WHEN SUM(COALESCE(total_fill_shares, 0)) = 0 THEN NULL
            ELSE SUM(COALESCE(average_fill_price, 0) * COALESCE(total_fill_shares, 0))
                 / SUM(COALESCE(total_fill_shares, 0))
        END                                   AS average_fill_price,
        MIN(first_fill_time)                  AS first_fill_time,
        MAX(last_fill_time)                   AS last_fill_time,
        MAX(primary_source)                   AS primary_source,
        MAX(source_priority)                  AS source_priority,
        MAX(refresh_strategy)                 AS refresh_strategy,
        MAX(source_refreshed_at)              AS source_refreshed_at,
        MAX(source_lineage)                   AS source_lineage
    FROM route_history
    GROUP BY OrderId, order_as_of_date;

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

-- order_history 索引由 route_history 的索引覆盖（idx_route_history_date 已在 route_history 上）
-- 如需专用 order_history 排序/过滤性能，可在此补充覆盖索引

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
--   order_history (PR-1: 现在是 route_history 的派生视图，非物理表)
--   route_history
--   route_event_history

-- Tables MOVED to ticker_registry.db:
--   ticker_repository
--   equ_ticker_registry
--   ccy_ticker_registry
--   ticker_date_mapping
--   order_label
