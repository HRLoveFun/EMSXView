export type CostViewModuleTab = 'overview' | 'analysis' | 'scorecard' | 'report' | 'monitoring' | 'configure';

export type ExportFormat = 'csv' | 'excel' | 'pdf';
export type ExportScope = 'current-page' | 'all-filtered' | 'selected-order';
export type ThresholdMode = 'absolute-above' | 'above' | 'below';
export type AlertSeverity = 'none' | 'normal' | 'warning' | 'critical';

export type CostViewMetricKey =
  | 'pnl_vwap_bps'
  | 'fill_pct'
  | 'volume_pct_adv20'
  | 'volume_pct_interval'
  | 'intraday_volatility'
  | 'price_movement_pct'
  | 'overfill_pct';

export interface ThresholdRule {
  key: CostViewMetricKey;
  label: string;
  mode: ThresholdMode;
  /** Warning 档：越过即进入异常清单（入清单覆盖范围与单档时期一致） */
  warning: number;
  /** Critical 档：仅用于分级标注；below 模式下更严格（数值更小） */
  critical: number;
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
  /** Report 页签默认包含的交易所清单；空数组表示包含全部市场 */
  reportExchanges: string[];
  /** 异常路由填充笔数下限（仅对 algo<>close 生效，默认 10） */
  minFillCount: number;
  /** 异常路由成交金额(USD)下限（对全部路由生效，默认 10000） */
  minNotionalUsd: number;
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
  // 003-tca-core-benchmarks: Phase 0 核心基准（可选，S7 未跑或 BDIB 缺失时为 null）
  p_arrival?: number | null;
  p_close?: number | null;
  arrival_cost_bps?: number | null;
  close_cost_bps?: number | null;
  opportunity_cost?: number | null;
  // 003-tca-core-benchmarks: Phase 1 Wagner IS / 风险 / 冲击（可选）
  p_decision?: number | null;
  delay_cost?: number | null;
  trading_cost?: number | null;
  wagner_is?: number | null;
  wagner_is_bps?: number | null;
  cost_stddev?: number | null;
  cost_p95?: number | null;
  cost_cvar?: number | null;
  order_duration_sec?: number | null;
  exec_rate_shares_per_min?: number | null;
  temp_impact_5min_bps?: number | null;
  temp_impact_10min_bps?: number | null;
  temp_impact_30min_bps?: number | null;
  perm_impact_bps?: number | null;
  recovery_truncated?: number | null;
  // 007-costview-report-filters: USD 成交金额换算（fx_rate 缺失则 USD 不换算）
  fx_rate?: number | null;
  // 时序数据
  time_series: TcaTimeSeriesPoint[];
}

// 003-tca-core-benchmarks: Order 级 TCA 汇总（route 聚合）
export interface TcaOrderAggregate {
  order_id: string;
  order_as_of_date: string;
  equ_ticker: string | null;
  exchange: string | null;
  side: string | null;
  broker: string | null;
  algo: string | null;
  trader_name: string | null;
  route_count: number;
  fill_count: number | null;
  delay_cost: number | null;
  trading_cost: number | null;
  opportunity_cost: number | null;
  wagner_is: number | null;
  p_arrival: number | null;
  p_decision: number | null;
  p_close: number | null;
  arrival_cost_bps: number | null;
  close_cost_bps: number | null;
  wagner_is_bps: number | null;
  temp_impact_5min_bps: number | null;
  temp_impact_10min_bps: number | null;
  temp_impact_30min_bps: number | null;
  perm_impact_bps: number | null;
  fill: number | null;
  route_shares: number | null;
  par_rate: number | null;
  cost_stddev: number | null;
  cost_p95: number | null;
  cost_cvar: number | null;
  order_duration_sec: number | null;
  exec_rate_shares_per_min: number | null;
  recovery_truncated: number | null;
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
  /** 缺口影响面：受影响 route 数 / 缺口成交金额（优先 USD，缺汇率时为本币） */
  missing_route_count?: number;
  missing_notional?: number;
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
  total_missing_routes?: number;
  total_missing_notional?: number;
  latest_gap_date: string | null;
}

export interface BdibHealthReport {
  start_date: string;
  end_date: string;
  /** ok = 已扫描；skipped = 超时/异常降级（与「无缺口」显式区分） */
  status?: 'ok' | 'skipped';
  reason?: 'timeout' | 'error';
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
  /** SLA 口径覆盖率（剔除结构内必然 NULL），与后端 sla_coverage 对齐 */
  sla_coverage?: Record<string, number | null>;
  null_counts: Record<string, number>;
  /** 每项指标为 NULL 的结构性原因（与后端 null_reasons 对齐） */
  null_reasons?: Record<string, string>;
}

export interface MetricCoverageReport {
  start_date: string;
  end_date: string;
  metrics: string[];
  bdib_dependent_metrics: string[];
  /** 期望内 NULL 指标集合（SLA 豁免） */
  expected_null_metrics?: string[];
  /** 全区间整体覆盖率（原始 / SLA） */
  overall?: { coverage: number | null; sla_coverage: number | null };
  group_by_exchange: boolean;
  /** 统计范围（与报告主体同一作用域） */
  scope?: TcaReportScope;
  rows: MetricCoverageRow[];
  data_source_warning?: string;
}

export interface TcaReportKpi {
  route_count: number;
  total_route_shares: number;
  weighted_pnl_vwap: number | null;
  avg_par_rate: number | null;
  avg_rpm: number | null;
  // 007: 总成交金额（本币 / USD 换算 / fx_rate 覆盖率）
  notional: number | null;
  notional_usd: number | null;
  /** USD 换算成功率（含 USD 路由与 fill_bdib 回填汇率） */
  fx_coverage: number | null;
  /** 无法换算 USD 而被排除的成交金额（本币口径） */
  notional_usd_excluded?: number | null;
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
  /** 纳入加权统计的路由数（pnl_vwap 非 NULL 且有成交额权重） */
  n_used?: number;
  weighted_pnl_vwap: number | null;
  avg_par_rate: number | null;
}

export interface TcaHistogramBucket {
  lower: number;
  upper: number;
  count: number;
}

/** pnl_vwap 分布（附样本量披露：分布仅覆盖 pnl_vwap 非 NULL 的路由） */
export interface TcaPnlHistogram {
  buckets: TcaHistogramBucket[];
  n_used: number;
  n_total: number;
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
  /** 报告作用域（全报告小节统一口径；未给 exchange 时为 BDIB 白名单口径） */
  scope?: TcaReportScope;
  /** 报告期语义：数据截至日 / 预设，供报告头自证（014） */
  as_of_date?: string | null;
  preset?: string | null;
}

/** 报告统计范围：默认 BDIB 白名单内全量；用户指定 exchange 时为用户口径 */
export interface TcaReportScope {
  mode: 'bdib_whitelist' | 'user_exchange_filter';
  exchanges: string[];
  /** 用户口径下被选中、但不在白名单内的市场（报告头告警依据） */
  out_of_scope: string[];
  /** 后端生成的作用域文案（如「BDIB 白名单内 26 个市场」） */
  label: string;
}

/** 单个加权指标的样本量与权重覆盖率（条数覆盖 ≠ 权重覆盖） */
export interface TcaWeightCoverageEntry {
  n_used: number;
  n_total: number;
  /** 样本（条数）覆盖率，已是百分数 0-100 */
  sample_pct: number | null;
  used_weight: number;
  total_weight: number;
  /** 权重（成交额）覆盖率，已是百分数 0-100 */
  weight_pct: number | null;
  /** 样本或权重覆盖低于阈值 → 该均值为子样本口径，结论仅供参考 */
  insufficient: boolean;
}

/** 加权 KPI 的覆盖披露（report.weight_coverage） */
export interface TcaWeightCoverage {
  metrics: Record<string, TcaWeightCoverageEntry>;
  /** 覆盖不足判定阈值（百分数） */
  threshold_pct: number;
  n_total: number;
  total_weight: number;
}

/** 可选市场清单（市场概览表使用） */
export interface TcaReportMarket {
  exchange: string;
  route_count: number;
  notional: number | null;
  notional_usd: number | null;
}

/** 额外 KPI（006 增补）：决策基准 / 实现短缺 / 风险 / 完成率 / 零成交 */
export interface TcaReportExtraKpis {
  arrival_cost_bps: number | null;
  wagner_is_bps: number | null;
  cost_stddev: number | null;
  cost_cvar: number | null;
  cost_p95: number | null;
  /** 组合级完成率 Σfill / ΣRouteShares（对大额未成交敏感） */
  avg_fill: number | null;
  /** 未成交金额缺口（USD 口径；价格走回退链 p_avg→p_arrival→p_decision→p_close） */
  unfilled_notional_usd?: number | null;
  /** 因价格回退链全空而无法计入缺口的路由数（缺口低估规模可见） */
  unfilled_notional_unpriced_routes?: number | null;
  /** 零成交路由数（fill 为 0/NULL 且有委托股数） */
  zero_fill_routes?: number;
  /** 零成交路由的委托金额（USD；完全未执行的机会成本规模） */
  zero_fill_notional_usd?: number | null;
}

/** 市场冲击分解（B2-2）：暂时冲击 5/10/30min + 永久冲击 + 收盘价成本 */
export interface TcaImpactBreakdown {
  temp_impact_5min_bps: number | null;
  temp_impact_10min_bps: number | null;
  temp_impact_30min_bps: number | null;
  perm_impact_bps: number | null;
  close_cost_bps: number | null;
  /** 因恢复窗口越界使用次日收盘价的路由数与占比 */
  recovery_truncated_count?: number | null;
  recovery_truncated_share?: number | null;
}

/** 异常路由命中规则 */
export interface TcaAnomalyHit {
  key: string;
  label: string;
  value: number;
  unit: 'bps' | 'percent';
  /** 命中档位：warning 入清单 / critical 需分级处置 */
  severity: 'warning' | 'critical';
}

/** 异常路由明细行（S6） */
export interface TcaAnomalyRow {
  date: string;
  order_id: string;
  route_id: string;
  ticker: string;
  exchange: string | null;
  side: string | null;
  notional_local: number | null;
  currency: string | null;
  notional_usd: number | null;
  broker: string | null;
  algo: string | null;
  completion_rate: number | null;
  par_rate: number | null;
  order_par_rate: number | null;
  fill_count: number | null;
  route_shares: number | null;
  fill: number | null;
  pnl_vwap: number | null;
  arrival_cost_bps: number | null;
  wagner_is_bps: number | null;
  opportunity_cost: number | null;
  unfilled: number | null;
  cost_cvar: number | null;
  order_duration_sec: number | null;
  recovery_truncated: number | null;
  hits: TcaAnomalyHit[];
  /** 路由级最严重档（critical 优先） */
  severity: 'warning' | 'critical';
  /** 数据质量标记：成交超过委托 / 订单参与率求和 >100% */
  overfill: boolean;
  order_par_gt100: boolean;
}

/** 异常路由明细（S6） */
export interface TcaAnomaly {
  count: number;
  rows: TcaAnomalyRow[];
  /** 因超出渲染上限被截断的条数（count 为全量命中数） */
  rows_truncated?: number;
  /** 全量明细 CSV 相对路径（HTML 报告导出时提供） */
  export_ref?: string | null;
}

/** 008: 按市场成交金额（美元）排名条目 */
export interface TcaMarketNotionalRankRow {
  exchange: string;
  name: string;
  route_count: number;
  notional: number | null;
  notional_usd: number | null;
}

/** 008: 按市场成交金额（美元）每日趋势点 */
export interface TcaMarketNotionalTrendPoint {
  date: string;
  exchange: string;
  name: string;
  notional_usd: number | null;
}

/** 多选筛选选项（007：distinct 值列表，供多选下拉使用） */
export interface TcaReportFilterOptions {
  brokers: string[];
  algos: string[];
  symbols: string[];
  /** 市场（Exchange）选项：与时间范围解耦，且已按 BDIB 白名单裁剪（与报告统计范围一致） */
  exchanges?: string[];
}

export interface TcaReportSummary {
  filters: TcaReportSummaryFilters;
  markets: TcaReportMarket[];
  filter_options: TcaReportFilterOptions;
  market_notional_ranking: TcaMarketNotionalRankRow[];
  market_notional_trend: TcaMarketNotionalTrendPoint[];
  kpi: TcaReportKpi | null;
  extra_kpis: TcaReportExtraKpis | null;
  impact_breakdown: TcaImpactBreakdown | null;
  /** 加权 KPI 的样本量与权重覆盖率（避免把覆盖子集均值读作全量水位） */
  weight_coverage?: TcaWeightCoverage | null;
  anomaly: TcaAnomaly | null;
  daily_series: TcaDailySeriesPoint[];
  rankings: { by_broker: TcaRankingRow[]; by_algo: TcaRankingRow[] };
  pnl_vwap_histogram: TcaPnlHistogram;
  pwp_curve: TcaPwpPoint[];
  metric_coverage: MetricCoverageReport | null;
  data_source_warning?: string;
}

/** 监控页持久化状态（时间范围预设 + 指标勾选） */
export interface MonitoringViewState {
  lastPreset: LastPreset;
  selectedMetrics: string[];
}