import type { MarketAlertSeverity, MarketTradingStatus, OrderIntentBenchmark } from './types';

// ── 交易状态（057 DL-29 追加）──────────────────────────────────────────────
// 休市时 mktdata 仍返回上一交易日镜像：状态徽标 + 是否置灰实时列都由这里统一口径

export function getMarketStatusText(status: MarketTradingStatus): string {
  switch (status) {
    case 'open': return 'Trading';
    case 'lunch': return 'Lunch';
    case 'pre': return 'Pre-open';
    case 'closed': return 'Closed';
    default: return 'Unknown';
  }
}

export function getMarketStatusTone(status: MarketTradingStatus): string {
  switch (status) {
    case 'open': return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700';
    case 'lunch': return 'border-amber-500/40 bg-amber-500/10 text-amber-700';
    case 'pre': return 'border-sky-500/40 bg-sky-500/10 text-sky-700';
    default: return 'border-border bg-muted/30 text-muted-foreground';
  }
}

/** 只有 open/lunch 才是「活的」行情；pre/closed 的实时列是镜像值，需置灰。 */
export function isLiveTrading(status: MarketTradingStatus): boolean {
  return status === 'open' || status === 'lunch';
}

export function renderMarketStatusBadge(status: MarketTradingStatus, time?: string | null) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-1 text-[11px] font-medium ${getMarketStatusTone(status)}`}
      title={time ? `Exchange local time ${time}` : 'Unknown exchange session'}
    >
      {getMarketStatusText(status)}
    </span>
  );
}

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value == null) return '—';
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

export function fmtCompact(value: number | null | undefined): string {
  if (value == null) return '—';
  return new Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export function fmtPercent(value: number | null | undefined, digits = 1): string {
  if (value == null) return '—';
  return `${value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}

export function getSeverityTone(severity: MarketAlertSeverity): string {
  switch (severity) {
    case 'critical': return 'border-red-500/30 bg-red-500/10 text-red-700';
    case 'warning': return 'border-amber-500/30 bg-amber-500/10 text-amber-700';
    case 'normal': return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700';
    default: return 'border-border bg-muted/30 text-muted-foreground';
  }
}

export function getSeverityText(severity: MarketAlertSeverity): string {
  switch (severity) {
    case 'critical': return 'Critical';
    case 'warning': return 'Warning';
    case 'normal': return 'Normal';
    default: return 'N/A';
  }
}

export function renderSeverityBadge(label: string, severity: MarketAlertSeverity) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-medium ${getSeverityTone(severity)}`}>
      {label}: {getSeverityText(severity)}
    </span>
  );
}

// PM Note 意图徽标（057 DL-01）：按 benchmark 分色，MIX 附带收盘比例
export function getIntentTone(benchmark: OrderIntentBenchmark): string {
  switch (benchmark) {
    case 'VWAP': return 'border-sky-500/30 bg-sky-500/10 text-sky-700';
    case 'CLOSE': return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-700';
    case 'MIX': return 'border-violet-500/30 bg-violet-500/10 text-violet-700';
    case 'SPECIAL': return 'border-amber-500/30 bg-amber-500/10 text-amber-700';
    default: return 'border-red-500/30 bg-red-500/10 text-red-700';
  }
}

export function getIntentLabel(benchmark: OrderIntentBenchmark, closePct: number | null): string {
  if (benchmark === 'MIX' && closePct != null) {
    return `MIX ${closePct}% @Close`;
  }
  return benchmark;
}

// 未匹配原因码 → 可读文本（与后端 export_parser 的 reason 码一一对应）
const UNMATCHED_REASON_TEXT: Record<string, string> = {
  empty_pm_note: 'Empty PM note',
  unknown_prefix: 'Unknown instruction prefix',
  missing_order_key: 'Missing order key (^ segment)',
};

export function getUnmatchedReasonText(reason: string): string {
  return UNMATCHED_REASON_TEXT[reason] ?? reason;
}
