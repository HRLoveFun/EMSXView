export type CostViewModuleTab = 'overview' | 'analysis' | 'scorecard' | 'report' | 'monitoring' | 'configure';

export type ExportFormat = 'csv' | 'excel' | 'pdf';
export type ExportScope = 'current-page' | 'all-filtered' | 'selected-order';
export type ThresholdMode = 'absolute-above' | 'above' | 'below';
export type AlertSeverity = 'none' | 'normal' | 'warning' | 'critical';

export type CostViewMetricKey =
  | 'tracking_error_bps'
  | 'fill_pct'
  | 'volume_pct_adv20'
  | 'volume_pct_interval'
  | 'intraday_volatility'
  | 'price_movement_pct';

export interface ThresholdRule {
  key: CostViewMetricKey;
  label: string;
  mode: ThresholdMode;
  warningThreshold: number;
  criticalThreshold: number;
  enabled: boolean;
  decimals: number;
  unit: 'bps' | 'percent';
  description: string;
}

export interface ExportDefaults {
  format: ExportFormat;
  scope: ExportScope;
  pdfIncludeCharts: boolean;
}

export interface CostViewConfig {
  rules: Record<CostViewMetricKey, ThresholdRule>;
  exportDefaults: ExportDefaults;
  updatedAt: string;
}

export interface CostViewFilterFormState {
  orderIds: string;
  algo: string;
  startDate: string;
  endDate: string;
  broker: string;
  symbol: string;
  warningOnly: boolean;
  limit: number;
}

export interface CostViewViewState {
  activeTab: CostViewModuleTab;
}

export interface CostViewExportState {
  lastExportAt: string | null;
  lastExportFormat: ExportFormat | null;
  lastExportScope: ExportScope | null;
}

export interface TcaFilterPayload {
  order_ids?: string[];
  algo?: string;
  start_date?: string;
  end_date?: string;
  broker?: string;
  symbol?: string;
}

export interface TcaAnalyzeRequest {
  filters: TcaFilterPayload;
  aggregation?: 'per_order' | 'aggregated';
  limit?: number;
  offset?: number;
}

export interface TcaTimeSeriesPoint {
  ts: string;
  close: number | null;
  fill_px: number | null;
  fill_volume: number | null;
  volume: number | null;
  cum_volume_pct: number | null;
  cum_fill_vwap: number | null;
  cum_vwap: number | null;
  cum_tracking_error: number | null;
}

export interface TcaRouteSummary {
  // 源值（17）
  order_id: string;
  route_id: string;
  order_as_of_date: string;
  exchange: string | null;
  account: string | null;
  equ_ticker: string | null;
  currency: string | null;
  side: string | null;
  amount: number | null;
  route_shares: number | null;
  type: string | null;
  limit_price: number | null;
  stop_price: number | null;
  broker: string | null;
  strategy_type: string | null;
  algo: string | null;
  trader_name: string | null;
  // 计算指标（18）：fill_count 为该路由下 FillId 的去重计数
  fill_count: number | null;
  fill: number | null;
  fill_continuous: number | null;
  fill_close: number | null;
  par_rate: number | null;
  par_rate_continuous: number | null;
  par_rate_close: number | null;
  p_avg: number | null;
  p_avg_continuous: number | null;
  pnl_vwap: number | null;
  pnl_vwap_continuous: number | null;
  rpm: number | null;
  rpm_continuous: number | null;
  pwp_5: number | string | null;
  pwp_10: number | string | null;
  pwp_15: number | string | null;
  pwp_20: number | string | null;
  pwp_25: number | string | null;
  // 时序数据
  time_series: TcaTimeSeriesPoint[];
}

export interface TcaReport {
  filters: TcaFilterPayload & { aggregation: string; limit: number; offset: number };
  total_orders: number;
  offset: number;
  limit: number;
  generated_at: string;
  orders: TcaRouteSummary[];
}


export interface TriggerUpdateResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface StageInfo {
  name: 'initialization' | 'fill_fetch' | 'processing' | 'completion';
  label: string;
  progress: number;  // 0-100 within this stage
  detail?: string | null;  // 阶段明细（如 "Day 3/7: 2026-04-29 — 1245 rows"）
}

export interface UpdateStatusResponse {
  job_id: string;
  status: 'started' | 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  stage: StageInfo | null;
  overall_progress: number;  // 0-100 across all stages
  last_activity_at: string | null;
}

// ── Scorecard contracts ────────────────────────────────────────────────────

export type ScorecardCohort =
  | 'broker'
  | 'strategy'
  | 'broker_strategy'
  | 'asset_class'
  | 'time_of_day'
  | 'liquidity_adv20'
  | 'volatility';

export interface ScorecardRequestPayload {
  cohort: ScorecardCohort;
  filters: TcaFilterPayload;
  min_sample_size?: number;
  max_orders?: number;
}

export interface ScorecardCohortMetrics {
  cohort_key: string;
  cohort_label: string;
  sample_size: number;
  order_count: number;
  avg_tracking_error_bps: number | null;
  median_tracking_error_bps: number | null;
  p95_tracking_error_bps: number | null;
  stddev_tracking_error_bps: number | null;
  avg_fill_pct: number | null;
  avg_volume_pct_interval: number | null;
  avg_volume_pct_adv20: number | null;
  avg_daily_volatility: number | null;
  avg_intraday_volatility: number | null;
  avg_price_movement_pct: number | null;
  data_quality_ratio: number;
  sample_size_warning: boolean;
  anomaly_flags: string[];
}

export interface ScorecardReport {
  filters: {
    cohort: ScorecardCohort;
    order_ids: string[] | null;
    algo: string | null;
    start_date: string | null;
    end_date: string | null;
    broker: string | null;
    symbol: string | null;
    min_sample_size: number;
    max_orders: number;
  };
  cohort: ScorecardCohort;
  min_sample_size: number;
  total_orders_considered: number;
  total_orders_capped: boolean;
  cohorts: ScorecardCohortMetrics[];
  generated_at: string;
  data_source_warning: string | null;
}

export interface ScorecardFormState {
  cohort: ScorecardCohort;
  minSampleSize: number;
  maxOrders: number;
}

// ── Monitoring / Report contracts（对应 /api/tca/monitoring/* 响应）──────────

export type LastPreset = 'day' | 'week' | 'month' | 'quarter' | 'year';

export type BdibHealthStatus = 'ok' | 'partial' | 'missing' | 'unrecoverable';

export interface BdibHealthDateEntry {
  date: string;
  fill_tickers: number;
  bdib_tickers: number;
  coverage_pct: number;
  missing_ticker_count: number;
  missing_tickers: string[];
  sqlite_rows: number;
  parquet_rows: number;
  status: BdibHealthStatus;
  retention_days_left: number;
}

export interface BdibHealthSummary {
  total_dates: number;
  ok_dates: number;
  partial_dates: number;
  missing_dates: number;
  unrecoverable_dates: number;
  recoverable_gap_dates: number;
  total_missing_tickers: number;
  latest_gap_date: string | null;
}

export interface BdibHealthReport {
  start_date: string;
  end_date: string;
  retention_days: number;
  dates: BdibHealthDateEntry[];
  summary: BdibHealthSummary;
  data_source_warning?: string;
}

export interface MetricCoverageRow {
  date: string;
  exchange: string | null;
  total_routes: number;
  coverage: Record<string, number | null>;
  null_counts: Record<string, number>;
}

export interface MetricCoverageReport {
  start_date: string;
  end_date: string;
  metrics: string[];
  bdib_dependent_metrics: string[];
  group_by_exchange: boolean;
  rows: MetricCoverageRow[];
  data_source_warning?: string;
}

export interface TcaReportKpi {
  route_count: number;
  total_route_shares: number;
  weighted_pnl_vwap: number | null;
  avg_par_rate: number | null;
  avg_rpm: number | null;
}

export interface TcaDailySeriesPoint {
  date: string;
  route_count: number;
  weighted_pnl_vwap: number | null;
  avg_par_rate: number | null;
}

export interface TcaRankingRow {
  name: string;
  route_count: number;
  weighted_pnl_vwap: number | null;
  avg_par_rate: number | null;
}

export interface TcaHistogramBucket {
  lower: number;
  upper: number;
  count: number;
}

export interface TcaPwpPoint {
  rate: number;
  avg_pwp: number | null;
}

export interface TcaReportSummaryFilters {
  start_date: string;
  end_date: string;
  broker: string | null;
  algo: string | null;
  symbol: string | null;
  exchange: string | null;
  metrics: string[];
}

export interface TcaReportSummary {
  filters: TcaReportSummaryFilters;
  kpi: TcaReportKpi | null;
  daily_series: TcaDailySeriesPoint[];
  rankings: { by_broker: TcaRankingRow[]; by_algo: TcaRankingRow[] };
  pnl_vwap_histogram: TcaHistogramBucket[];
  pwp_curve: TcaPwpPoint[];
  metric_coverage: MetricCoverageReport | null;
  data_source_warning?: string;
}

/** 监控页持久化状态（时间范围预设 + 指标勾选） */
export interface MonitoringViewState {
  lastPreset: LastPreset;
  selectedMetrics: string[];
}