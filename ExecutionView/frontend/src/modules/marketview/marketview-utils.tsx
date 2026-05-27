import type { MarketAlertSeverity } from './types';

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
