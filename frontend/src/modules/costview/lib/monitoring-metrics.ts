/** TCA 监控指标常量 — 与后端 CostView/src/monitoring/metric_coverage.py 白名单保持一致 */

/** 38 项计算指标白名单（顺序与后端 COMPUTED_METRICS 一致；003-tca-core-benchmarks 扩展） */
export const ALL_TCA_METRICS = [
  // 原有 18 项
  'fill_count', 'fill', 'fill_continuous', 'fill_close',
  'par_rate', 'par_rate_continuous', 'par_rate_close',
  'p_avg', 'p_avg_continuous',
  'pnl_vwap', 'pnl_vwap_continuous',
  'RPM', 'RPM_continuous',
  'pwp_5', 'pwp_10', 'pwp_15', 'pwp_20', 'pwp_25',
  // Phase 0 核心基准
  'p_arrival', 'p_close', 'arrival_cost_bps', 'close_cost_bps',
  'opportunity_cost',
  // Phase 1 Wagner IS / 风险 / 冲击
  'p_decision', 'delay_cost', 'trading_cost', 'wagner_is', 'wagner_is_bps',
  'cost_stddev', 'cost_p95', 'cost_cvar',
  'order_duration_sec', 'exec_rate_shares_per_min',
  'temp_impact_5min_bps', 'temp_impact_10min_bps', 'temp_impact_30min_bps',
  'perm_impact_bps', 'recovery_truncated',
] as const;

export type TcaMetricName = (typeof ALL_TCA_METRICS)[number];

/** 依赖 BDIB 行情的指标（BDIB 缺失时 NULL 属预期） */
export const BDIB_DEPENDENT_METRICS: ReadonlySet<string> = new Set([
  // 原有 BDIB 依赖项
  'par_rate', 'par_rate_continuous', 'par_rate_close',
  'pnl_vwap', 'pnl_vwap_continuous',
  'pwp_5', 'pwp_10', 'pwp_15', 'pwp_20', 'pwp_25',
  // Phase 0/1 依赖 BDIB bar 的指标
  'p_arrival', 'p_close', 'arrival_cost_bps', 'close_cost_bps',
  'opportunity_cost',
  'p_decision', 'delay_cost', 'trading_cost', 'wagner_is', 'wagner_is_bps',
  'temp_impact_5min_bps', 'temp_impact_10min_bps', 'temp_impact_30min_bps',
  'perm_impact_bps',
]);

/** 期望内 NULL 指标（SLA 豁免）：closing_auction + single_fill 类，NULL 属结构性预期，非数据缺口 */
export const EXPECTED_NULL_METRICS: ReadonlySet<string> = new Set([
  'p_avg_continuous', 'par_rate_continuous', 'pnl_vwap_continuous', 'RPM_continuous',
  'cost_stddev', 'cost_p95', 'cost_cvar', 'order_duration_sec', 'exec_rate_shares_per_min',
]);

/** 每项指标为 NULL 的结构性原因（与后端 metric_coverage.METRIC_NULL_REASON 对齐） */
export const METRIC_NULL_REASON: Record<string, string> = {
  fill_count: 'source', fill: 'source', fill_continuous: 'source', fill_close: 'source',
  par_rate: 'bdib_cutoff', par_rate_continuous: 'closing_auction', par_rate_close: 'bdib_cutoff',
  p_avg: 'source', p_avg_continuous: 'closing_auction',
  pnl_vwap: 'bdib_cutoff', pnl_vwap_continuous: 'closing_auction',
  RPM: 'source', RPM_continuous: 'closing_auction',
  pwp_5: 'bdib_cutoff', pwp_10: 'bdib_cutoff', pwp_15: 'bdib_cutoff', pwp_20: 'bdib_cutoff', pwp_25: 'bdib_cutoff',
  p_arrival: 'bdib_missing', p_close: 'bdib_missing', arrival_cost_bps: 'bdib_missing',
  close_cost_bps: 'bdib_missing', opportunity_cost: 'bdib_missing',
  p_decision: 'bdib_missing', delay_cost: 'bdib_missing', trading_cost: 'bdib_missing',
  wagner_is: 'bdib_missing', wagner_is_bps: 'bdib_missing',
  cost_stddev: 'single_fill', cost_p95: 'single_fill', cost_cvar: 'single_fill',
  order_duration_sec: 'single_fill', exec_rate_shares_per_min: 'single_fill',
  temp_impact_5min_bps: 'bdib_cutoff', temp_impact_10min_bps: 'bdib_cutoff', temp_impact_30min_bps: 'bdib_cutoff',
  perm_impact_bps: 'next_day_close', recovery_truncated: 'source',
  fx_rate: 'fx',
};
export type MetricNullReason = typeof METRIC_NULL_REASON;
