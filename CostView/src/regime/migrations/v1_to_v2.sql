-- ============================================================================
-- Migration v1 → v2: fix fill_regime_labels primary key
-- WHY: processed_fills table has composite PK (OrderId, RouteId, FillId, order_as_of_date).
--      v1 used only fill_id in fill_regime_labels which cannot uniquely join back to source
--      (FillId alone is not unique in EMSX feed). Switch to the full composite key.
-- DATE: 2026-04-27
-- DATA  : v1 fill_regime_labels has 0 rows (verified) so no data migration needed.
-- ============================================================================

-- Drop dependent objects first (view references the table; index attached to it).
DROP VIEW IF EXISTS regime_status;
DROP INDEX IF EXISTS idx_fill_labels_date_market;
DROP TABLE IF EXISTS fill_regime_labels;

-- ============================================================================
-- fill_regime_labels  (v2)
-- PURPOSE   : Per-fill regime tags (vol/liq/trend/macro) for downstream attribution.
-- WRITTEN BY: regime.fill_regime_tagger (Stage 8)
-- READ BY   : ExecutionView TCA queries, attribution module
-- GRAIN     : One row per (OrderId, RouteId, FillId, order_as_of_date_iso, config_version)
-- NOTE      : composite key matches processed_fills PK (cross-DB, no FK).
--             order_as_of_date_iso is 'YYYY-MM-DD' (regime-layer standard);
--             tagger converts legacy 'YYYYMMDD' → 'YYYY-MM-DD' on the fly.
-- ============================================================================
CREATE TABLE fill_regime_labels (
    OrderId                 TEXT NOT NULL,
    RouteId                 TEXT NOT NULL,
    FillId                  TEXT NOT NULL,
    order_as_of_date_iso    TEXT NOT NULL CHECK (order_as_of_date_iso LIKE '____-__-__'),
    config_version          TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    market_code             TEXT NOT NULL,
    vol_regime              TEXT,
    liq_regime              TEXT,
    trend_regime            TEXT,
    macro_event_window      INTEGER NOT NULL DEFAULT 0 CHECK (macro_event_window IN (0,1)),
    time_bucket             TEXT,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date_iso, config_version),
    FOREIGN KEY (market_code)    REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (config_version) REFERENCES audit_regime_config_versions(version_id)
);
CREATE INDEX idx_fill_labels_date_market
    ON fill_regime_labels(trade_date, market_code, config_version);

-- Recreate the status view (table list unchanged but column references updated).
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
    SELECT 'audit_regime_config_versions', COUNT(*), NULL, NULL, MAX(created_at)
    FROM audit_regime_config_versions
    UNION ALL
    SELECT 'audit_pipeline_runs', COUNT(*),
           MIN(date(run_started_at)), MAX(date(run_started_at)), MAX(run_started_at)
    FROM audit_pipeline_runs;
