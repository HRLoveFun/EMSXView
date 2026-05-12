-- ============================================================================
-- Migration v2 -> v3: M2 attribution layer
-- WHY: Add per-fill attribution metrics (IS / VWAP slippage + reversal) and a
--      separate config-version table so attribution params (bench_method,
--      reversal windows, winsor_pct, ADV window, bootstrap_n) can drift
--      without touching the regime classifier params (audit_regime_config_versions).
-- DATE: 2026-04-28
-- DATA : v2 has 0 rows in any new table; pure additive migration.
-- ============================================================================

-- ============================================================================
-- audit_attribution_config_versions
-- PURPOSE   : Snapshot of attribution-pipeline parameters (benchmarks, reversal
--             windows, winsorization, bootstrap settings) for reproducibility.
-- WRITTEN BY: attribution.config (seed_default + activate)
-- READ BY   : attribution.metrics, attribution.aggregator, scripts/run_attribution.py
-- GRAIN     : One row per parameter set version_id; is_active=1 marks current.
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_attribution_config_versions (
    version_id            TEXT PRIMARY KEY,
    created_at            TIMESTAMP NOT NULL,
    is_active             INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
    -- Benchmarks computed per fill. Comma-separated list of method tokens.
    -- Supported tokens: 'arrival_mid', 'interval_vwap'.
    bench_methods         TEXT NOT NULL DEFAULT 'arrival_mid,interval_vwap',
    -- Reversal lookforward windows in minutes. Comma-separated.
    reversal_windows_min  TEXT NOT NULL DEFAULT '1,5,30',
    -- Two-sided winsorization fraction applied per metric per cell.
    winsor_pct            REAL NOT NULL DEFAULT 0.01 CHECK (winsor_pct >= 0 AND winsor_pct < 0.2),
    -- ADV rolling window for %ADV calculations (calendar days, not trading days).
    adv_window_days       INTEGER NOT NULL DEFAULT 30 CHECK (adv_window_days BETWEEN 5 AND 252),
    -- Bootstrap resamples for cell CI computations.
    bootstrap_n           INTEGER NOT NULL DEFAULT 5000 CHECK (bootstrap_n BETWEEN 100 AND 100000),
    -- Cells with n below this get suppressed (NULL means no recommendation).
    min_cell_n            INTEGER NOT NULL DEFAULT 30 CHECK (min_cell_n >= 5),
    description           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_attribution_config
    ON audit_attribution_config_versions(is_active) WHERE is_active = 1;


-- ============================================================================
-- fill_attribution_metrics
-- PURPOSE   : Per-fill execution-quality metrics (slippage vs arrival mid and
--             interval VWAP, plus 1/5/30-min post-fill reversal). Joinable to
--             fill_regime_labels by composite PK for regime-conditional analysis.
-- WRITTEN BY: attribution.metrics (Stage 10)
-- READ BY   : attribution.aggregator (Stage 11), notebooks/research_notes/*
-- GRAIN     : One row per (OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
-- DERIVED   : is_bps          = side * (fill_price / arrival_px - 1) * 1e4
--             vwap_bps        = side * (fill_price / interval_vwap - 1) * 1e4
--             reversal_Nm_bps = side * (mid_at_fill_plus_N - fill_price) / fill_price * 1e4
-- NOTE      : Cross-DB join to processed_fills (no FK). config_version refs
--             audit_attribution_config_versions, NOT regime config.
-- ============================================================================
CREATE TABLE IF NOT EXISTS fill_attribution_metrics (
    OrderId                 TEXT NOT NULL,
    RouteId                 TEXT NOT NULL,
    FillId                  TEXT NOT NULL,
    order_as_of_date_iso    TEXT NOT NULL CHECK (order_as_of_date_iso LIKE '____-__-__'),
    config_version          TEXT NOT NULL,

    -- Denormalized join keys (handy for queries; also lets aggregator skip
    -- the cross-DB join when only attribution metrics are needed).
    market_code             TEXT NOT NULL,
    broker                  TEXT,
    algo                    TEXT,
    side                    INTEGER NOT NULL CHECK (side IN (-1, 1)),  -- 1=buy, -1=sell
    fill_shares             REAL NOT NULL CHECK (fill_shares > 0),
    fill_price              REAL NOT NULL CHECK (fill_price > 0),

    -- Order-level context (same value across all fills of one route).
    route_shares            REAL,
    pct_adv                 REAL CHECK (pct_adv IS NULL OR pct_adv >= 0),
    participation_rate      REAL CHECK (participation_rate IS NULL OR (participation_rate >= 0 AND participation_rate <= 5)),

    -- Benchmarks (cached so aggregator does not re-fetch raw_bdib).
    arrival_px              REAL,
    interval_vwap           REAL,
    mid_at_fill             REAL,
    mid_fill_plus_1m        REAL,
    mid_fill_plus_5m        REAL,
    mid_fill_plus_30m       REAL,

    -- Metrics in basis points (side-aware: positive = adverse to taker).
    is_bps                  REAL,
    vwap_bps                REAL,
    reversal_1m_bps         REAL,
    reversal_5m_bps         REAL,
    reversal_30m_bps        REAL,

    -- Bitmask of missing benchmarks: 1=arrival, 2=interval_vwap, 4=mid@fill,
    -- 8=mid+1m, 16=mid+5m, 32=mid+30m. 0 = all present.
    data_quality_flags      INTEGER NOT NULL DEFAULT 0,

    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,

    PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date_iso, config_version),
    FOREIGN KEY (config_version) REFERENCES audit_attribution_config_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_attr_date_market_broker
    ON fill_attribution_metrics(order_as_of_date_iso, market_code, broker, algo, config_version);
CREATE INDEX IF NOT EXISTS idx_attr_broker_algo
    ON fill_attribution_metrics(broker, algo, config_version);


-- ============================================================================
-- Recreate regime_status view to include the two new tables.
-- ============================================================================
DROP VIEW IF EXISTS regime_status;
CREATE VIEW regime_status AS
    SELECT 'ref_market_mapping' AS table_name, COUNT(*) AS rows,
           NULL AS min_date, NULL AS max_date, MAX(synced_at) AS last_write
    FROM ref_market_mapping
    UNION ALL
    SELECT 'ref_macro_event_dict', COUNT(*), NULL, NULL, NULL FROM ref_macro_event_dict
    UNION ALL
    SELECT 'ref_macro_event_calendar', COUNT(*), MIN(event_date), MAX(event_date), MAX(synced_at)
    FROM ref_macro_event_calendar
    UNION ALL
    SELECT 'daily_market_index', COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
    FROM daily_market_index
    UNION ALL
    SELECT 'daily_vol_regime', COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
    FROM daily_vol_regime
    UNION ALL
    SELECT 'daily_liquidity_regime', COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
    FROM daily_liquidity_regime
    UNION ALL
    SELECT 'daily_trend_regime', COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
    FROM daily_trend_regime
    UNION ALL
    SELECT 'fill_regime_labels', COUNT(*), MIN(trade_date), MAX(trade_date), MAX(ingested_at)
    FROM fill_regime_labels
    UNION ALL
    SELECT 'fill_attribution_metrics', COUNT(*),
           MIN(order_as_of_date_iso), MAX(order_as_of_date_iso), MAX(ingested_at)
    FROM fill_attribution_metrics
    UNION ALL
    SELECT 'audit_regime_config_versions', COUNT(*), NULL, NULL, MAX(created_at)
    FROM audit_regime_config_versions
    UNION ALL
    SELECT 'audit_attribution_config_versions', COUNT(*), NULL, NULL, MAX(created_at)
    FROM audit_attribution_config_versions
    UNION ALL
    SELECT 'audit_pipeline_runs', COUNT(*),
           MIN(date(run_started_at)), MAX(date(run_started_at)), MAX(run_started_at)
    FROM audit_pipeline_runs;
