-- ============================================================================
-- EMSXView Index Optimizations — Supplemental Covering & Composite Indexes
-- ============================================================================
-- Apply with: sqlite3 <db_path> < this_file
-- All indexes use IF NOT EXISTS — safe to run on live databases.
-- ============================================================================

-- ------------------------------------------------------------------
-- processed_fills.db — TCA Core Query Covering Indexes
-- ------------------------------------------------------------------

-- Main fill query: WHERE order_as_of_date = ? AND OrderId = ?
-- Covering index avoids heap lookup for the most common column set
CREATE INDEX IF NOT EXISTS idx_proc_date_order_cover
    ON processed_fills(order_as_of_date, OrderId, RouteId, FillId,
                       EquTicker, Exchange, Currency, Side,
                       FillPrice, FillShares, Broker, Algo);

-- Order-level fill statistics: SUM(FillShares) / Amount
CREATE INDEX IF NOT EXISTS idx_proc_date_order_shares
    ON processed_fills(order_as_of_date, OrderId, FillShares, Amount);

-- Route-level participation query
CREATE INDEX IF NOT EXISTS idx_proc_date_route_pct
    ON processed_fills(order_as_of_date, OrderId, RouteId, FillShares, FillPrice);

-- ------------------------------------------------------------------
-- processed_fills.db — Aggregated Fills Time-Series Indexes
-- ------------------------------------------------------------------

-- 10-second aggregation: chart rendering hot path
CREATE INDEX IF NOT EXISTS idx_agg_10s_order_route_ts_cover
    ON agg_fills_10s(OrderId, RouteId, mkt_timestamp, order_as_of_date,
                      vwap_10s, volume_10s, fill_px_10s);

-- 1-minute aggregation: deprecated but maintained
CREATE INDEX IF NOT EXISTS idx_agg_1min_order_route_ts
    ON agg_fills_1min(OrderId, RouteId, mkt_timestamp_1min, order_as_of_date);

-- ------------------------------------------------------------------
-- processed_fills.db — Execution History Indexes
-- ------------------------------------------------------------------

-- Order history: date-scoped summary queries with pagination
CREATE INDEX IF NOT EXISTS idx_order_history_date_order_cover
    ON order_history(order_as_of_date, OrderId, EquTicker, Algo, Broker,
                     FillPct, TotalVolume, avg_price);

-- Route event history: audit trail time-range query
CREATE INDEX IF NOT EXISTS idx_route_event_route_ts_type
    ON route_event_history(OrderId, RouteId, event_timestamp, event_type);

-- Date-range scans on route_event_history (bulk export / backfill)
CREATE INDEX IF NOT EXISTS idx_route_event_order_date
    ON route_event_history(OrderId, order_as_of_date);

-- ------------------------------------------------------------------
-- fill_bdib.db — Integrated Fill+BDIB Time-Series Indexes
-- ------------------------------------------------------------------

-- Chart rendering: time-series for a specific route
CREATE INDEX IF NOT EXISTS idx_fill_bdib_date_order_route_ts
    ON fill_bdib(order_as_of_date, OrderId, RouteId, mkt_timestamp,
                 close, fill_px, fill_volume, cum_volume_pct, cum_slippage_bps);

-- TCA metrics lookup: LAST row per route
CREATE INDEX IF NOT EXISTS idx_fill_bdib_date_order_route_last
    ON fill_bdib(order_as_of_date, OrderId, RouteId, mkt_timestamp DESC,
                 cum_slippage_bps, cum_vwap, cum_tracking_error);

-- Ticker-scoped market aggregation
CREATE INDEX IF NOT EXISTS idx_fill_bdib_ticker_date_route
    ON fill_bdib(equ_ticker, order_as_of_date, OrderId, RouteId,
                 cum_volume_pct, cum_slippage_bps);

-- ------------------------------------------------------------------
-- raw_bdib.db — Market Data Context Queries
-- ------------------------------------------------------------------

-- Interval-bounded bar lookup: WHERE equ_ticker=? AND order_as_of_date=? AND mkt_timestamp BETWEEN ? AND ?
CREATE INDEX IF NOT EXISTS idx_raw_bdib_ticker_date_ts_close
    ON raw_bdib(equ_ticker, order_as_of_date, mkt_timestamp, close, volume);

-- Daily summary: ADV multi-window lookup
CREATE INDEX IF NOT EXISTS idx_daily_summary_ticker_date_adv
    ON bdib_daily_summary(equ_ticker, trade_date, adv_5d, adv_20d,
                          daily_volatility, intraday_volatility);

-- ------------------------------------------------------------------
-- processed_raw_bdib.db — Derived Fields Queries
-- ------------------------------------------------------------------

-- Ticker+date range for derived metric computation
CREATE INDEX IF NOT EXISTS idx_proc_raw_bdib_ticker_date_vwap
    ON processed_raw_bdib(equ_ticker, order_as_of_date, mkt_timestamp,
                          close, vwap, volume);

-- ------------------------------------------------------------------
-- raw_fills.db — Ingestion Dedup & Order Stats
-- ------------------------------------------------------------------

-- Date-scoped fill count / integrity check
CREATE INDEX IF NOT EXISTS idx_raw_date_order_fill
    ON raw_fills(order_as_of_date, OrderId, RouteId, FillId, FillShares, Amount);

-- Ticker+date for downstream BDIB selection
CREATE INDEX IF NOT EXISTS idx_raw_ticker_date_amount
    ON raw_fills(Ticker, order_as_of_date, Amount, Side);

-- ------------------------------------------------------------------
-- regime.db — Attribution Query Indexes (in addition to existing)
-- ------------------------------------------------------------------

-- Broker+algo aggregation: scorecard builder hot path
CREATE INDEX IF NOT EXISTS idx_attr_date_broker_algo_metrics
    ON fill_attribution_metrics(order_as_of_date_iso, broker, algo, config_version,
                                implementation_shortfall_bps, vwap_slippage_bps);

-- Fill regime labels: per-fill lookup during TCA report assembly
CREATE INDEX IF NOT EXISTS idx_fill_labels_date_order
    ON fill_regime_labels(order_as_of_date_iso, OrderId, RouteId, FillId);
