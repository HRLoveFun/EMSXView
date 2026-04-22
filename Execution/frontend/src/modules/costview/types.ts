export type CostViewModuleTab = 'overview' | 'analysis' | 'configure';

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

export interface TcaRouteDetail {
  order_id: string;
  route_id: string;
  order_as_of_date: string;
  broker: string | null;
  side: string | null;
  start_time: string | null;
  end_time: string | null;
  fill_pct: number | null;
  exec_price: number | null;
  interval_vwap: number | null;
  tracking_error_bps: number | null;
  volume_pct_interval: number | null;
  time_series: TcaTimeSeriesPoint[];
}

export interface TcaOrderSummary {
  order_id: string;
  order_as_of_date: string;
  equ_ticker: string | null;
  side: string | null;
  algo: string | null;
  start_time: string | null;
  end_time: string | null;
  fill_pct: number | null;
  exec_price: number | null;
  interval_vwap: number | null;
  tracking_error_bps: number | null;
  volume_pct_interval: number | null;
  volume_pct_adv5: number | null;
  volume_pct_adv20: number | null;
  intraday_volatility: number | null;
  price_movement_pct: number | null;
  data_quality_warning: boolean;
  routes: TcaRouteDetail[];
}

export interface TcaReport {
  filters: TcaFilterPayload & { aggregation: string; limit: number; offset: number };
  total_orders: number;
  offset: number;
  limit: number;
  generated_at: string;
  orders: TcaOrderSummary[];
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