-- ============================================================================
-- Migration v0 → v1: initial regime layer schema
-- WHY: bootstrap regime classification database (M1)
-- DATE: 2026-04-27
-- ============================================================================
-- Notes:
--   * All dates are TEXT 'YYYY-MM-DD'.
--   * 4-layer prefix: ref_ / daily_ / fill_ / audit_ (upper layers read lower).
--   * Non-ref tables carry source_version + ingested_at (traceability).
--   * Parameterized analytical outputs include config_version in PK (append-only,
--     reproducibility). Current params resolved via audit_regime_config_versions.is_active=1.
-- ============================================================================


-- ============================================================================
-- ref_market_mapping
-- PURPOSE   : Single source of truth for market-level reference (vol index, benchmark,
--             trading session). Synced from CostView/data/market_mapping.json.
-- WRITTEN BY: regime.sync_market_mapping (planned step 5 helper)
-- READ BY   : daily_market_index loader, fill_regime_tagger, validators, status view
-- GRAIN     : One row per market_code (Bloomberg exchange code; EUR-denominated → 'EU')
-- ============================================================================
CREATE TABLE IF NOT EXISTS ref_market_mapping (
    market_code             TEXT PRIMARY KEY,
    description             TEXT NOT NULL,
    currency                TEXT NOT NULL,
    vol_index               TEXT,                       -- nullable: degrade to realized-vol
    benchmark               TEXT NOT NULL,
    session_open            TEXT NOT NULL,              -- 'HH:MM' local
    session_close           TEXT NOT NULL,              -- 'HH:MM' local
    lunch_start             TEXT,                       -- nullable
    lunch_end               TEXT,                       -- nullable
    closing_auction_start   TEXT NOT NULL,              -- 'HH:MM' local
    source_file_version     TEXT NOT NULL,              -- _schema.version from json
    synced_at               TIMESTAMP NOT NULL,
    CHECK (length(market_code) BETWEEN 2 AND 4)
);


-- ============================================================================
-- ref_macro_event_dict
-- PURPOSE   : Catalog of macro event types and their default severity / window.
-- WRITTEN BY: regime.sync_macro_event_dict (loads CostView/data/macro_event_dict.json)
-- READ BY   : ref_macro_event_calendar validator, fill_regime_tagger
-- GRAIN     : One row per event_type
-- ============================================================================
CREATE TABLE IF NOT EXISTS ref_macro_event_dict (
    event_type              TEXT PRIMARY KEY,
    default_severity        TEXT NOT NULL CHECK (default_severity IN ('low','medium','high')),
    default_window_days     INTEGER NOT NULL CHECK (default_window_days >= 0),
    description             TEXT NOT NULL
);


-- ============================================================================
-- ref_macro_event_calendar
-- PURPOSE   : Per-market macro event calendar (FOMC, CPI, NFP, holidays, etc.).
-- WRITTEN BY: regime.sync_macro_calendar (loads CostView/data/macro_calendar.csv)
-- READ BY   : fill_regime_tagger (for macro_event_window flag)
-- GRAIN     : One row per (event_date, market_code, event_type)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ref_macro_event_calendar (
    event_date              TEXT NOT NULL CHECK (event_date LIKE '____-__-__'),
    market_code             TEXT NOT NULL,
    event_type              TEXT NOT NULL,
    severity                TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    window_days             INTEGER NOT NULL DEFAULT 1 CHECK (window_days >= 0),
    description             TEXT,
    source_file_version     TEXT NOT NULL,
    synced_at               TIMESTAMP NOT NULL,
    PRIMARY KEY (event_date, market_code, event_type),
    FOREIGN KEY (market_code) REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (event_type)  REFERENCES ref_macro_event_dict(event_type)
);
CREATE INDEX IF NOT EXISTS idx_macro_calendar_market_date
    ON ref_macro_event_calendar(market_code, event_date);


-- ============================================================================
-- daily_market_index
-- PURPOSE   : Per-market daily benchmark + vol-index features (raw, not classified).
-- WRITTEN BY: regime.market_index_loader (Stage 7a)
-- READ BY   : daily_vol_regime, daily_liquidity_regime, daily_trend_regime calculators
-- GRAIN     : One row per (market_code, trade_date)
-- MNEMONICS : PX_LAST, VOLATILITY_20D, VOLATILITY_60D, TURNOVER,
--             MOV_AVG_30D, MOV_AVG_50D, MOV_AVG_200D, RSI_30D
-- DERIVED   : high_252d, low_252d  -- rolling 252-day max/min of px_last (NOT a mnemonic)
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_market_index (
    market_code             TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    px_last                 REAL,
    vol_index_value         REAL,
    turnover                REAL,
    vol_20d                 REAL,
    vol_60d                 REAL,
    mov_avg_30d             REAL,
    mov_avg_50d             REAL,
    mov_avg_200d            REAL,
    rsi_30d                 REAL CHECK (rsi_30d IS NULL OR (rsi_30d BETWEEN 0 AND 100)),
    high_252d               REAL,
    low_252d                REAL,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (market_code, trade_date),
    FOREIGN KEY (market_code) REFERENCES ref_market_mapping(market_code)
);


-- ============================================================================
-- audit_regime_config_versions
-- PURPOSE   : Parameter set registry for regime classification. Append-only.
-- WRITTEN BY: regime.config admin (manual or migration); pipeline reads is_active=1
-- READ BY   : All daily_*_regime calculators, fill_regime_tagger, status view
-- GRAIN     : One row per parameter set version
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_regime_config_versions (
    version_id              TEXT PRIMARY KEY,            -- e.g. 'v2026.04.27'
    created_at              TIMESTAMP NOT NULL,
    is_active               INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
    vol_method              TEXT NOT NULL,               -- 'vix_percentile' | 'realized_vol_zscore'
    vol_thresholds_json     TEXT NOT NULL,               -- JSON: {low,normal,high,extreme}
    liq_method              TEXT NOT NULL,               -- 'turnover_zscore'
    liq_thresholds_json     TEXT NOT NULL,
    trend_method            TEXT NOT NULL,               -- 'ma_alignment' | 'rsi_combo'
    trend_thresholds_json   TEXT NOT NULL,
    time_buckets_json       TEXT NOT NULL,               -- JSON list of bucket defs
    description             TEXT
);
-- Enforce: at most ONE active config at a time
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_regime_config
    ON audit_regime_config_versions(is_active) WHERE is_active = 1;


-- ============================================================================
-- daily_vol_regime
-- PURPOSE   : Daily volatility regime classification (low/normal/high/extreme).
-- WRITTEN BY: regime.vol_regime (Stage 7b)
-- READ BY   : fill_regime_tagger, frontend regime dashboards
-- GRAIN     : One row per (market_code, trade_date, config_version)  -- append-only
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_vol_regime (
    market_code             TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    config_version          TEXT NOT NULL,
    vol_regime              TEXT NOT NULL CHECK (vol_regime IN ('low','normal','high','extreme')),
    vol_score               REAL,
    method                  TEXT NOT NULL,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (market_code, trade_date, config_version),
    FOREIGN KEY (market_code)    REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (config_version) REFERENCES audit_regime_config_versions(version_id)
);


-- ============================================================================
-- daily_liquidity_regime
-- PURPOSE   : Daily liquidity regime classification (thin/normal/thick).
-- WRITTEN BY: regime.liquidity_regime (Stage 7c)
-- READ BY   : fill_regime_tagger
-- GRAIN     : One row per (market_code, trade_date, config_version)
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_liquidity_regime (
    market_code             TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    config_version          TEXT NOT NULL,
    liq_regime              TEXT NOT NULL CHECK (liq_regime IN ('thin','normal','thick')),
    turnover_zscore         REAL,
    method                  TEXT NOT NULL,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (market_code, trade_date, config_version),
    FOREIGN KEY (market_code)    REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (config_version) REFERENCES audit_regime_config_versions(version_id)
);


-- ============================================================================
-- daily_trend_regime
-- PURPOSE   : Daily trend regime classification (downtrend/range/uptrend).
-- WRITTEN BY: regime.trend_regime (Stage 7d)
-- READ BY   : fill_regime_tagger
-- GRAIN     : One row per (market_code, trade_date, config_version)
-- DERIVED   : dist_52w_high_pct = (px_last - high_252d) / high_252d
-- ============================================================================
CREATE TABLE IF NOT EXISTS daily_trend_regime (
    market_code             TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    config_version          TEXT NOT NULL,
    trend_regime            TEXT NOT NULL CHECK (trend_regime IN ('downtrend','range','uptrend')),
    ma_signal               TEXT,
    rsi_30d                 REAL CHECK (rsi_30d IS NULL OR (rsi_30d BETWEEN 0 AND 100)),
    dist_52w_high_pct       REAL,
    method                  TEXT NOT NULL,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (market_code, trade_date, config_version),
    FOREIGN KEY (market_code)    REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (config_version) REFERENCES audit_regime_config_versions(version_id)
);


-- ============================================================================
-- fill_regime_labels
-- PURPOSE   : Per-fill regime tags (vol/liq/trend/macro) for downstream attribution.
-- WRITTEN BY: regime.fill_regime_tagger (Stage 8)
-- READ BY   : ExecutionView TCA queries, attribution module
-- GRAIN     : One row per (fill_id, config_version)  -- append-only across param drift
-- NOTE      : fill_id lives in CostView/data/processed_fills.db (cross-DB, no FK).
-- ============================================================================
CREATE TABLE IF NOT EXISTS fill_regime_labels (
    fill_id                 TEXT NOT NULL,
    trade_date              TEXT NOT NULL CHECK (trade_date LIKE '____-__-__'),
    market_code             TEXT NOT NULL,
    config_version          TEXT NOT NULL,
    vol_regime              TEXT,
    liq_regime              TEXT,
    trend_regime            TEXT,
    macro_event_window      INTEGER NOT NULL DEFAULT 0 CHECK (macro_event_window IN (0,1)),
    time_bucket             TEXT,
    source_version          TEXT NOT NULL,
    ingested_at             TIMESTAMP NOT NULL,
    PRIMARY KEY (fill_id, config_version),
    FOREIGN KEY (market_code)    REFERENCES ref_market_mapping(market_code),
    FOREIGN KEY (config_version) REFERENCES audit_regime_config_versions(version_id)
);
CREATE INDEX IF NOT EXISTS idx_fill_labels_date_market
    ON fill_regime_labels(trade_date, market_code, config_version);


-- ============================================================================
-- audit_pipeline_runs
-- PURPOSE   : Run journal — every regime stage execution writes one row. Recovery
--             jobs query this first to find resumable / failed batches.
-- WRITTEN BY: BaseStage.run() wrapper (regime stages)
-- READ BY   : backfill scripts, status view, CLI diagnostics
-- GRAIN     : One row per stage execution
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_pipeline_runs (
    run_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_name              TEXT NOT NULL,
    config_version          TEXT,
    target_start_date       TEXT,
    target_end_date         TEXT,
    rows_written            INTEGER,
    rows_updated            INTEGER,
    status                  TEXT NOT NULL CHECK (status IN ('running','success','failed','rollback')),
    error_message           TEXT,
    run_started_at          TIMESTAMP NOT NULL,
    run_finished_at         TIMESTAMP,
    duration_sec            REAL,
    host                    TEXT,
    schema_version          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_stage_started
    ON audit_pipeline_runs(stage_name, run_started_at DESC);


-- ============================================================================
-- regime_status (VIEW)
-- PURPOSE   : One-glance health: row count, date range, last ingest per table.
-- READ BY   : validate_regime.py CLI, frontend ops panel
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
    SELECT 'audit_regime_config_versions', COUNT(*), NULL, NULL, MAX(created_at)
    FROM audit_regime_config_versions
    UNION ALL
    SELECT 'audit_pipeline_runs', COUNT(*),
           MIN(date(run_started_at)), MAX(date(run_started_at)), MAX(run_started_at)
    FROM audit_pipeline_runs;
