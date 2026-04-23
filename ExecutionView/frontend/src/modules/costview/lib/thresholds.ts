import type {
  AlertSeverity,
  CostViewConfig,
  CostViewMetricKey,
  ExportDefaults,
  TcaOrderSummary,
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
  order: TcaOrderSummary,
  key: CostViewMetricKey,
): number | null | undefined {
  return order[key];
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
  order: TcaOrderSummary,
  config: CostViewConfig,
): Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> {
  const entries: Array<{ key: CostViewMetricKey; label: string; severity: AlertSeverity; value: number }> = [];

  for (const rule of Object.values(config.rules)) {
    const value = getMetricValue(order, rule.key);
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
  order: TcaOrderSummary,
  config: CostViewConfig,
): AlertSeverity {
  const severities = Object.values(config.rules)
    .map((rule) => evaluateThreshold(rule, getMetricValue(order, rule.key)));

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

export function countAlertOrders(orders: TcaOrderSummary[], config: CostViewConfig): number {
  return orders.filter((order) => {
    const severity = getHighestOrderSeverity(order, config);
    return severity === 'warning' || severity === 'critical';
  }).length;
}

export function averageMetric(
  orders: TcaOrderSummary[],
  key: CostViewMetricKey,
): number | null {
  const values = orders
    .map((order) => getMetricValue(order, key))
    .filter((value): value is number => value != null && Number.isFinite(value));

  if (!values.length) return null;

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}