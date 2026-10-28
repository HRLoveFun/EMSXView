export type MarketAlertSeverity = 'none' | 'normal' | 'warning' | 'critical';
type MarketAlertFilter = 'all' | 'warning' | 'critical';
type MarketSortField =
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
type MarketSortDirection = 'asc' | 'desc';

interface MarketAlert {
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

interface MarketSnapshotFilters {
  min_adv_20d: number | null;
  min_total_volume: number | null;
  min_daily_volatility: number | null;
  min_intraday_volatility: number | null;
  liquidity_alert: MarketAlertFilter;
  volatility_alert: MarketAlertFilter;
}

interface MarketSnapshotSort {
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

interface MarketCandidateRow {
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

interface IntradayFeatureBucket {
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

// ── EMSX 导出盘前单（057 DL-01） ──────────────────────────────

export type OrderIntentBenchmark = 'VWAP' | 'CLOSE' | 'MIX' | 'SPECIAL' | 'UNMAPPED';

export interface OrderIntent {
  order_key: string;
  benchmark: OrderIntentBenchmark;
  close_pct: number | null;
  raw_note: string;
  intent_source: string;
  valid_from: string;
  export_ts: string;
  unmatched_reason: string | null;
}

export interface ExportOrderRow {
  code: string;
  exch_code: string;
  name: string;
  side: string;
  qty: number | null;
  ccy: string;
  status: string;
  fill_qty: number | null;
  pct_filled: number | null;
  q_pct_5d_adv: number | null;
  q_pct_tdy: number | null;
  rem_bal_pct_avg_cls_auct_vol: number | null;
  working_val_usd: number | null;
  value_usd: number | null;
  chg_pct_dtdy: number | null;
  last_px_vs_vwap_bps: number | null;
  earn_rpt_time: string | null;
  ex_dvd_flag: string | null;
  brkr_code: string;
  create_time: string;
  pm_note: string;
  intent: OrderIntent;
  extra_fields: Record<string, string>;
}

export interface UnmatchedOrder {
  code: string;
  pm_note: string;
  reason: string;
}

export interface PreTradeOrdersPayload {
  exported_at: string;
  export_file_name: string;
  order_count: number;
  intent_coverage_pct: number;
  intent_mapping_version: string;
  orders: ExportOrderRow[];
  unmatched: UnmatchedOrder[];
}

// ── 057 DL-14：盘前单装配（四路产物） ──────────────────────

export interface PreTradeBoardItem {
  equ_ticker: string;
  order_key: string;
  benchmark: OrderIntentBenchmark;
  close_pct: number | null;
  qty: number | null;
  log_volume_z: number | null;
  vol_percentile: number | null;
  adv5_adv60_ratio: number | null;
  market_code: string | null;
  liq_regime: string | null;
  vol_regime: string | null;
  expected_cost_bps: number | null;
  timing_risk_bps: number | null;
  in_domain: boolean;
  model_version: string | null;
  model_calibrated: boolean;
  data_gaps: string[];
}

export type OrderIntentSource = 'intraday' | 'export' | 'none';
export type SnapshotSource = 'formal' | 'intraday' | 'none';

export interface UnmatchedIntent {
  order_key: string;
  equ_ticker: string;
  pm_note: string;
  reason: string;
}

export interface FreshnessEntry {
  dataset: string;
  as_of: string;
  lag_minutes: number;
}

export interface PreTradeBoardPayload {
  trade_date: string | null;
  export_file_name: string;
  schema_version: string;
  items: PreTradeBoardItem[];
  // 057 DL-07 读侧（081/082）：来源、覆盖率、未匹配清单、数据集新鲜度
  intent_source: OrderIntentSource;
  intent_coverage_pct: number;
  unmatched: UnmatchedIntent[];
  freshness: FreshnessEntry[];
  snapshot_source: SnapshotSource;
  generated_at: string;
}

// 057 DL-15：盘中市场状态（实时列数据源；开关关闭时 enabled=false）
export interface MarketStateFlag {
  code: string;
  severity: string;
  evidence: string;
}

export interface MarketStateTickerState {
  equ_ticker: string;
  as_of: string;
  bid: number | null;
  ask: number | null;
  last: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  spread_bps: number | null;
  spread_vs_baseline_bps: number | null;
  /** v2：实时涨跌幅（百分数，1.23 表示 +1.23%） */
  pct_change_1d: number | null;
  cumulative_volume_ratio: number | null;
  flags: MarketStateFlag[];
  schema_version: string;
}

export interface MarketStateSnapshot {
  as_of: string;
  enabled: boolean;
  tickers: MarketStateTickerState[];
  thresholds: Record<string, unknown>;
  schema_version: string;
}

/** 实时数据来源状态：live = WS 推送；polling = WS 不可用、REST 轮询。 */
export type LiveMarketStateStatus = 'idle' | 'connecting' | 'live' | 'polling';

/** 供表格消费的实时行情索引（按 equ_ticker 对齐日度快照行）。 */
export interface LiveQuotes {
  byTicker: Map<string, MarketStateTickerState>;
  status: LiveMarketStateStatus;
  enabled: boolean;
  asOf: string | null;
}

// ── 057 DL-29：固定筛选池池板（量价 / 难度 / 成本同屏） ──────────

export interface PoolBoardAssumptions {
  notional_usd: number;
  annual_vol_pct: number;
  duration_min: number;
  model_calibrated: boolean;
  note: string;
}

export interface PoolBoardRow {
  equ_ticker: string;
  daily_close: number | null;
  total_volume: number | null;
  adv_20d: number | null;
  volume_vs_adv20_pct: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  liquidity_alert: MarketAlertSeverity;
  volatility_alert: MarketAlertSeverity;
  log_volume_z: number | null;
  vol_percentile: number | null;
  adv5_adv60_ratio: number | null;
  expected_cost_bps: number | null;
  timing_risk_bps: number | null;
  in_domain: boolean;
  model_version: string | null;
  data_gaps: string[];
}

export interface PoolBoardPayload {
  trade_date: string | null;
  pool_id: string;
  row_count: number;
  assumptions: PoolBoardAssumptions;
  rows: PoolBoardRow[];
  generated_at: string;
}
