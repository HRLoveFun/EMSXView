import type {
  AlertSeverity,
  CostViewConfig,
  CostViewMetricKey,
  ExportDefaults,
  ScorecardCohortMetrics,
  TcaRouteSummary,
  ThresholdRule,
} from '../types';

const DEFAULT_RULES: Record<CostViewMetricKey, ThresholdRule> = {
  tracking_error_bps: {
    key: 'tracking_error_bps',
    label: 'Tracking Error',
    mode: 'absolute-above',
    warningThreshold: 10,
    criticalThreshold: 25,
    enabled: true,
    decimals: 1,
    unit: 'bps',
    description: 'Absolute tracking error in basis points.',
  },
  fill_pct: {
    key: 'fill_pct',
    label: 'Fill %',
    mode: 'below',
    warningThreshold: 80,
    criticalThreshold: 50,
    enabled: true,
    decimals: 1,
    unit: 'percent',
    description: 'Lower fill rate indicates incomplete execution.',
  },
  volume_pct_adv20: {
    key: 'volume_pct_adv20',
    label: 'Vol % ADV20',
    mode: 'above',
    warningThreshold: 5,
    criticalThreshold: 10,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Participation relative to 20-day ADV.',
  },
  volume_pct_interval: {
    key: 'volume_pct_interval',
    label: 'Vol % Interval',
    mode: 'above',
    warningThreshold: 20,
    criticalThreshold: 35,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Participation within the execution interval.',
  },
  intraday_volatility: {
    key: 'intraday_volatility',
    label: 'Intraday Volatility',
    mode: 'above',
    warningThreshold: 2.5,
    criticalThreshold: 4,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Annualized intraday volatility.',
  },
  price_movement_pct: {
    key: 'price_movement_pct',
    label: 'Price Move',
    mode: 'absolute-above',
    warningThreshold: 1,
    criticalThreshold: 2.5,
    enabled: true,
    decimals: 2,
    unit: 'percent',
    description: 'Absolute price movement during the order interval.',
  },
};

const DEFAULT_EXPORTS: ExportDefaults = {
  format: 'csv',
  scope: 'current-page',
  pdfIncludeCharts: false,
};

export function createDefaultCostViewConfig(): CostViewConfig {
  return {
    rules: structuredClone(DEFAULT_RULES),
    exportDefaults: { ...DEFAULT_EXPORTS },
    updatedAt: new Date().toISOString(),
  };
}

export function getMetricValue(
  route: TcaRouteSummary,
  key: CostViewMetricKey,
): number | null | undefined {
  switch (key) {
    // tracking_error_bps 由后端新指标 pnl_vwap（basis points）承载
    case 'tracking_error_bps': return route.pnl_vwap;
    // fill_pct 由后端新指标 fill 承载（百分比，0-100）
    case 'fill_pct': return route.fill;
    // volume_pct_adv20 由后端参与率 par_rate 承载（0-1 小数，阈值按百分比 0-100）
    case 'volume_pct_adv20': return route.par_rate != null ? route.par_rate * 100 : null;
    // volume_pct_interval 由连续参与率 par_rate_continuous 承载（0-1 小数，阈值按百分比 0-100）
    case 'volume_pct_interval': return route.par_rate_continuous != null ? route.par_rate_continuous * 100 : null;
    // intraday_volatility 由 pnl_vwap_continuous 代理（basis points，阈值按百分比 0-100）
    case 'intraday_volatility': return route.pnl_vwap_continuous != null ? route.pnl_vwap_continuous / 100 : null;
    // price_movement_pct 由 rpm 代理（百分比，0-100）
    case 'price_movement_pct': return route.rpm;
    default: return undefined;
  }
}

export function evaluateThreshold(
  rule: ThresholdRule,
  rawValue: number | null | undefined,
): AlertSeverity {
  if (!rule.enabled || rawValue == null || Number.isNaN(rawValue)) {
    return 'none';
  }

  const value = rule.mode === 'absolute-above' ? Math.abs(rawValue) : rawValue;

  if (rule.mode === 'below') {
    if (value <= rule.criticalThreshold) return 'critical';
    if (value <= rule.warningThreshold) return 'warning';
    return 'normal';
  }

  if (value >= rule.criticalThreshold) return 'critical';
  if (value >= rule.warningThreshold) return 'warning';
  return 'normal';
}

export function getOrderAlertDetails(
  route: TcaRouteSummary,
  config: CostViewConfig,
): Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> {
  const entries: Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> = [];

  for (const rule of Object.values(config.rules)) {
    const value = getMetricValue(route, rule.key);
    const severity = evaluateThreshold(rule, value);
    if ((severity === 'warning' || severity === 'critical') && value != null) {
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
  return routes.filter((route) => {
    const severity = getHighestOrderSeverity(route, config);
    return severity === 'warning' || severity === 'critical';
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
    evaluateThreshold(config.rules.tracking_error_bps, cohort.avg_tracking_error_bps ?? null),
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