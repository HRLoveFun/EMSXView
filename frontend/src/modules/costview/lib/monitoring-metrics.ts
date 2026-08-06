/** TCA 监控指标常量 — 与后端 CostView/src/monitoring/metric_coverage.py 白名单保持一致 */

/** 18 项计算指标白名单（顺序与后端 COMPUTED_METRICS 一致） */
export const ALL_TCA_METRICS = [
  'fill_count', 'fill', 'fill_continuous', 'fill_close',
  'par_rate', 'par_rate_continuous', 'par_rate_close',
  'p_avg', 'p_avg_continuous',
  'pnl_vwap', 'pnl_vwap_continuous',
  'RPM', 'RPM_continuous',
  'pwp_5', 'pwp_10', 'pwp_15', 'pwp_20', 'pwp_25',
] as const;

export type TcaMetricName = (typeof ALL_TCA_METRICS)[number];

/** 依赖 BDIB 行情的指标（BDIB 缺失时 NULL 属预期） */
export const BDIB_DEPENDENT_METRICS: ReadonlySet<string> = new Set([
  'par_rate', 'par_rate_continuous', 'par_rate_close',
  'pnl_vwap', 'pnl_vwap_continuous',
  'pwp_5', 'pwp_10', 'pwp_15', 'pwp_20', 'pwp_25',
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
};
