export type MarketAlertSeverity = 'none' | 'normal' | 'warning' | 'critical';
export type MarketAlertFilter = 'all' | 'warning' | 'critical';
export type MarketSortField =
  | 'equ_ticker'
  | 'daily_close'
  | 'daily_volatility'
  | 'intraday_volatility'
  | 'total_volume'
  | 'adv_5d'
  | 'adv_20d'
  | 'volume_vs_adv20_pct'
  | 'liquidity_alert'
  | 'volatility_alert';
export type MarketSortDirection = 'asc' | 'desc';

export interface MarketAlert {
  code: string;
  category: string;
  severity: MarketAlertSeverity;
  message: string;
}

export interface MarketStockPool {
  pool_id: string;
  label: string;
  description: string;
  default_sort_by: MarketSortField;
  default_sort_direction: MarketSortDirection;
}

export interface MarketSnapshotFilters {
  min_adv_20d: number | null;
  min_total_volume: number | null;
  min_daily_volatility: number | null;
  min_intraday_volatility: number | null;
  liquidity_alert: MarketAlertFilter;
  volatility_alert: MarketAlertFilter;
}

export interface MarketSnapshotSort {
  field: MarketSortField;
  direction: MarketSortDirection;
}

export interface MarketSnapshotRow {
  equ_ticker: string;
  trade_date: string;
  daily_close: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  total_volume: number | null;
  adv_5d: number | null;
  adv_20d: number | null;
  volume_vs_adv20_pct: number | null;
  liquidity_alert: MarketAlertSeverity;
  volatility_alert: MarketAlertSeverity;
  alert_count: number;
  alerts: MarketAlert[];
}

export interface MarketCandidateRow {
  equ_ticker: string;
  trade_date: string;
  daily_close: number | null;
  total_volume: number | null;
  adv_20d: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  liquidity_alert: MarketAlertSeverity;
  volatility_alert: MarketAlertSeverity;
  alerts: MarketAlert[];
}

export interface MarketCandidatePayload {
  source: string;
  handoff_target: string;
  trade_date: string | null;
  pool_id: string;
  pool_label: string | null;
  filters: MarketSnapshotFilters;
  sort: MarketSnapshotSort;
  row_count: number;
  candidates: MarketCandidateRow[];
}

export interface MarketSnapshotPayload {
  trade_date: string | null;
  row_count: number;
  available_pools: MarketStockPool[];
  active_pool_id: string;
  filters: MarketSnapshotFilters;
  sort: MarketSnapshotSort;
  rows: MarketSnapshotRow[];
  candidate_payload: MarketCandidatePayload;
}

export interface MarketSnapshotRequest {
  limit?: number;
  trade_date?: string;
  pool_id?: string;
  min_adv_20d?: number;
  min_total_volume?: number;
  min_daily_volatility?: number;
  min_intraday_volatility?: number;
  liquidity_alert?: MarketAlertFilter;
  volatility_alert?: MarketAlertFilter;
  sort_by?: MarketSortField;
  sort_direction?: MarketSortDirection;
}

export type IntradayBucketMinutes = 5 | 10 | 15 | 30 | 60;

export interface IntradayFeatureBucket {
  bucket_start: string;
  bucket_end: string;
  bar_count: number;
  volume: number | null;
  cumulative_volume: number | null;
  cumulative_volume_pct: number | null;
  vwap: number | null;
  close: number | null;
  high: number | null;
  low: number | null;
  realized_vol_annualized: number | null;
  volume_vs_adv20_pct: number | null;
}

export interface IntradayTickerFeatures {
  equ_ticker: string;
  trade_date: string;
  bar_count: number;
  first_bar_time: string | null;
  last_bar_time: string | null;
  total_volume: number | null;
  daily_vwap: number | null;
  daily_close: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  adv_20d: number | null;
  open_window_volume: number | null;
  open_window_vwap: number | null;
  open_window_share_pct: number | null;
  close_window_volume: number | null;
  close_window_vwap: number | null;
  close_window_share_pct: number | null;
  volume_vs_adv20_pct: number | null;
  buckets: IntradayFeatureBucket[];
}

export interface IntradayFeatureSnapshot {
  trade_date: string | null;
  bucket_minutes: number;
  ticker_count: number;
  missing_tickers: string[];
  tickers: IntradayTickerFeatures[];
}

export interface IntradayFeatureRequest {
  tickers: string[];
  trade_date?: string;
  bucket_minutes?: IntradayBucketMinutes;
}