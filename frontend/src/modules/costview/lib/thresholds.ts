import type {
  AlertSeverity,
  CostViewConfig,
  CostViewMetricKey,
  ExportDefaults,
  ScorecardCohortMetrics,
  TcaRouteSummary,
  ThresholdRule,
} from '../types';

/** 本地默认规则：后端 /api/tca/monitoring/anomaly-thresholds 为唯一真相源（ADR-0018），
 *  此处仅作离线兜底；warning 决定是否进入异常清单，critical 仅用于分级标注。
 *  注：后端的 order_par_gt100 规则（订单参与率求和超限）依赖订单级聚合，
 *  前端 route 级数据无法计算，故不在此列，仅由后端异常清单承载。 */
const DEFAULT_RULES: Record<CostViewMetricKey, ThresholdRule> = {
  pnl_vwap_bps: {
    key: 'pnl_vwap_bps',
    // 014: 原 tracking_error_bps 重命名 —— 该规则实为 |pnl_vwap| 阈值（ADR-0018）
    label: 'Pnl VWAP (bps)',
    mode: 'absolute-above',
    warning: 10,
    critical: 25,
    enabled: true,
    decimals: 1,
    unit: 'bps',
    description: 'Absolute pnl_vwap in basis points.',
  },
  fill_pct: {
    key: 'fill_pct',
    label: 'Fill %',
    mode: 'below',
    warning: 80,
    critical: 50,
    enabled: true,
    decimals: 1,
    unit: 'percent',
    description: 'Lower fill rate indicates incomplete execution.',
  },
  volume_pct_adv20: {
    key: 'volume_pct_adv20',
    label: 'Vol % ADV20',
    mode: 'above',
    warning: 5,
    critical: 10,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Participation relative to 20-day ADV.',
  },
  volume_pct_interval: {
    key: 'volume_pct_interval',
    label: 'Vol % Interval',
    mode: 'above',
    warning: 20,
    critical: 35,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Participation within the execution interval.',
  },
  intraday_volatility: {
    key: 'intraday_volatility',
    label: 'Intraday Volatility',
    mode: 'above',
    warning: 2.5,
    critical: 4,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Annualized intraday volatility.',
  },
  price_movement_pct: {
    key: 'price_movement_pct',
    label: 'Price Move',
    mode: 'absolute-above',
    warning: 1,
    critical: 2.5,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Absolute price movement during the order interval.',
  },
  // 数据质量探针：成交超过委托（fill > RouteShares）属数据矛盾
  overfill_pct: {
    key: 'overfill_pct',
    label: 'Overfill %',
    mode: 'above',
    warning: 100,
    critical: 110,
    enabled: true,
    decimals: 1,
    unit: 'percent',
    description: 'Fill exceeds route shares (data inconsistency).',
  },
};

const DEFAULT_EXPORTS: ExportDefaults = {
  format: 'csv',
  scope: 'current-page',
  pdfIncludeCharts: false,
};

/** 默认 Report 交易所范围：空数组表示包含全部市场 */
const DEFAULT_REPORT_EXCHANGES: string[] = [];

export function createDefaultCostViewConfig(): CostViewConfig {
  return {
    rules: structuredClone(DEFAULT_RULES),
    exportDefaults: { ...DEFAULT_EXPORTS },
    reportExchanges: [...DEFAULT_REPORT_EXCHANGES],
    minFillCount: 10,
    minNotionalUsd: 10000,
    updatedAt: new Date().toISOString(),
  };
}

export function getMetricValue(
  route: TcaRouteSummary,
  key: CostViewMetricKey,
): number | null | undefined {
  switch (key) {
    // pnl_vwap_bps 由后端指标 pnl_vwap（basis points）承载（原 tracking_error_bps）
    case 'pnl_vwap_bps': return route.pnl_vwap;
    // fill_pct（完成率）由成交股数 fill 与目标股数 RouteShares 换算（0-1 小数 ×100 → 阈值按百分比 0-100）
    case 'fill_pct': return route.fill != null && route.route_shares ? (route.fill / route.route_shares) * 100 : null;
    // volume_pct_adv20 由后端参与率 par_rate 承载（0-1 小数，阈值按百分比 0-100）
    case 'volume_pct_adv20': return route.par_rate != null ? route.par_rate * 100 : null;
    // volume_pct_interval 由连续参与率 par_rate_continuous 承载（0-1 小数，阈值按百分比 0-100）
    case 'volume_pct_interval': return route.par_rate_continuous != null ? route.par_rate_continuous * 100 : null;
    // intraday_volatility 由 pnl_vwap_continuous 代理（basis points，阈值按百分比 0-100）
    case 'intraday_volatility': return route.pnl_vwap_continuous != null ? route.pnl_vwap_continuous / 100 : null;
    // price_movement_pct 由 rpm 代理（百分比，0-100）
    case 'price_movement_pct': return route.rpm;
    // overfill_pct（数据质量）：成交超过委托的百分比（fill / RouteShares × 100）
    case 'overfill_pct': return route.fill != null && route.route_shares ? (route.fill / route.route_shares) * 100 : null;
    default: return undefined;
  }
}

/** 阈值判定（ADR-0018 两档）：越过 warning 入异常清单，越过 critical 标注为严重。
 *  below 模式下 critical 阈值更小（更严格）。 */
export function evaluateThreshold(
  rule: ThresholdRule,
  rawValue: number | null | undefined,
): AlertSeverity {
  if (!rule.enabled || rawValue == null || Number.isNaN(rawValue)) {
    return 'none';
  }

  const value = rule.mode === 'absolute-above' ? Math.abs(rawValue) : rawValue;

  if (rule.mode === 'below') {
    if (value <= rule.critical) return 'critical';
    return value <= rule.warning ? 'warning' : 'normal';
  }

  if (value >= rule.critical) return 'critical';
  return value >= rule.warning ? 'warning' : 'normal';
}

export function getOrderAlertDetails(
  route: TcaRouteSummary,
  config: CostViewConfig,
): Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> {
  const entries: Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> = [];

  for (const rule of Object.values(config.rules)) {
    const value = getMetricValue(route, rule.key);
    const severity = evaluateThreshold(rule, value);
    // warning 及以上即视为异常（与后端入清单边界一致）
    if ((severity === 'critical' || severity === 'warning') && value != null) {
      entries.push({
        key: rule.key,
        label: rule.label,
        severity,
        value,
      });
    }
  }

  return entries;
}

export function getHighestOrderSeverity(
  route: TcaRouteSummary,
  config: CostViewConfig,
): AlertSeverity {
  const severities = Object.values(config.rules)
    .map((rule) => evaluateThreshold(rule, getMetricValue(route, rule.key)));

  if (severities.includes('critical')) return 'critical';
  if (severities.includes('warning')) return 'warning';
  if (severities.includes('normal')) return 'normal';
  return 'none';
}

export function getSeverityTone(severity: AlertSeverity): string {
  switch (severity) {
    case 'critical':
      return 'text-red-600 bg-red-500/10 border-red-500/30';
    case 'warning':
      return 'text-amber-600 bg-amber-500/10 border-amber-500/30';
    case 'normal':
      return 'text-emerald-600 bg-emerald-500/10 border-emerald-500/30';
    default:
      return 'text-muted-foreground bg-muted/40 border-border';
  }
}

export function getSeverityText(severity: AlertSeverity): string {
  switch (severity) {
    case 'critical':
      return 'Critical';
    case 'warning':
      return 'Warning';
    case 'normal':
      return 'Normal';
    default:
      return 'N/A';
  }
}

export function countAlertOrders(routes: TcaRouteSummary[], config: CostViewConfig): number {
  // 入异常清单的边界为 warning 档（覆盖范围与后端一致）
  return routes.filter((route) => {
    const severity = getHighestOrderSeverity(route, config);
    return severity === 'critical' || severity === 'warning';
  }).length;
}

export function averageMetric(
  routes: TcaRouteSummary[],
  key: CostViewMetricKey,
): number | null {
  const values = routes
    .map((route) => getMetricValue(route, key))
    .filter((value): value is number => value != null && Number.isFinite(value));

  if (!values.length) return null;

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

/**
 * Evaluate a cohort against the same threshold rules applied to individual
 * orders. The scorecard uses average metrics per cohort, so we reuse the
 * detail-view thresholds to keep alert semantics consistent across views.
 */
export function evaluateCohortSeverity(
  cohort: ScorecardCohortMetrics,
  config: CostViewConfig,
): AlertSeverity {
  if (cohort.sample_size_warning) {
    // Cohort below sample-size floor — never auto-escalate to critical based
    // on unstable averages. Surface as warning instead.
    return 'warning';
  }
  const severities: AlertSeverity[] = [
    evaluateThreshold(config.rules.pnl_vwap_bps, cohort.avg_tracking_error_bps ?? null),
    evaluateThreshold(config.rules.fill_pct, cohort.avg_fill_pct ?? null),
    evaluateThreshold(config.rules.volume_pct_adv20, cohort.avg_volume_pct_adv20 ?? null),
    evaluateThreshold(config.rules.volume_pct_interval, cohort.avg_volume_pct_interval ?? null),
    evaluateThreshold(config.rules.intraday_volatility, cohort.avg_intraday_volatility ?? null),
    evaluateThreshold(config.rules.price_movement_pct, cohort.avg_price_movement_pct ?? null),
  ];
  if (severities.includes('critical')) return 'critical';
  if (severities.includes('warning')) return 'warning';
  if (severities.includes('normal')) return 'normal';
  return 'none';
}

export function formatAnomalyFlag(flag: string): string {
  switch (flag) {
    case 'sample_size':
      return 'Small sample';
    case 'high_tracking_error':
      return 'High tracking error';
    case 'elevated_tracking_error':
      return 'Elevated tracking error';
    case 'tail_tracking_error':
      return 'Heavy tail (P95)';
    case 'low_fill_rate':
      return 'Low fill rate';
    case 'high_participation':
      return 'High ADV participation';
    case 'data_quality':
      return 'Data quality risk';
    default:
      return flag.replaceAll('_', ' ');
  }
}

/** 后端阈值 payload（ADR-0018 双档；threshold 为 ADR-0015 单档遗留写法，兼容读取） */
export interface BackendThresholdRule {
  mode: ThresholdRule['mode'];
  warning?: number;
  critical?: number;
  threshold?: number;
  enabled: boolean;
}

/**
 * 008/014: 以后端默认阈值合并覆盖本地规则。保留本地的中文标签 / 描述 / 小数位 / 单位，
 * 仅用后端值覆盖 mode / warning / critical / enabled（后端为唯一真相源）。
 * 兼容 ADR-0015 单档 payload：threshold 等价于 warning = critical。
 */
export function mergeBackendThresholds(
  backendRules: Record<string, BackendThresholdRule>,
): Record<CostViewMetricKey, ThresholdRule> {
  const base = createDefaultCostViewConfig().rules;
  const next = {} as Record<CostViewMetricKey, ThresholdRule>;
  for (const key of Object.keys(base) as CostViewMetricKey[]) {
    const backend = backendRules[key];
    const local = base[key];
    if (!backend) {
      next[key] = local;
      continue;
    }
    const single = backend.threshold;
    next[key] = {
      ...local,
      mode: backend.mode,
      warning: backend.warning ?? single ?? local.warning,
      critical: backend.critical ?? single ?? local.critical,
      enabled: backend.enabled,
    };
  }
  return next;
}