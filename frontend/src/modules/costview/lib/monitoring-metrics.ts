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

/** 指标中文说明（热力图 tooltip / 勾选列表 label） */
export const METRIC_LABELS: Record<string, string> = {
  fill_count: '成交笔数',
  fill: '成交率',
  fill_continuous: '连续时段成交率',
  fill_close: '收盘成交率',
  par_rate: '参与率',
  par_rate_continuous: '连续时段参与率',
  par_rate_close: '收盘参与率',
  p_avg: '成交均价',
  p_avg_continuous: '连续时段均价',
  pnl_vwap: 'VWAP 滑点',
  pnl_vwap_continuous: '连续时段 VWAP 滑点',
  RPM: '每分钟成交率',
  RPM_continuous: '连续时段 RPM',
  pwp_5: 'PWP@5%',
  pwp_10: 'PWP@10%',
  pwp_15: 'PWP@15%',
  pwp_20: 'PWP@20%',
  pwp_25: 'PWP@25%',
  // Phase 0 核心基准
  p_arrival: '到达价 P₀',
  p_close: '收盘价 Pn',
  arrival_cost_bps: '到达价成本',
  close_cost_bps: '收盘价成本',
  opportunity_cost: '机会成本',
  // Phase 1 Wagner IS / 风险 / 冲击
  p_decision: '决策价 Pd',
  delay_cost: '延迟成本',
  trading_cost: '交易成本',
  wagner_is: 'Wagner IS',
  wagner_is_bps: 'Wagner IS (bps)',
  cost_stddev: '成本标准差',
  cost_p95: '成本 P95',
  cost_cvar: '成本 CVaR',
  order_duration_sec: '订单历时',
  exec_rate_shares_per_min: '执行速率',
  temp_impact_5min_bps: '暂时冲击 5m',
  temp_impact_10min_bps: '暂时冲击 10m',
  temp_impact_30min_bps: '暂时冲击 30m',
  perm_impact_bps: '永久冲击',
  recovery_truncated: '恢复截断',
};
