/**
 * Shared formatting utilities for financial data display.
 * Centralised to avoid duplication across table/monitor components.
 */

// ─── Number formatting ──────────────────────────────────────────────────────

/** Format a number with locale-aware decimal places. Returns '—' for nullish. */
export function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—';
  return v.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format an integer with locale-aware grouping. Returns '—' for nullish. */
export function fmtInt(v: number | null | undefined): string {
  if (v == null) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

/** Format a percentage value (2 dp + '%'). Returns '—' for nullish. */
export function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return v.toFixed(2) + '%';
}

/** Format a dollar value with auto-scaling (K/M). Returns '—' for nullish. */
export function fmtDollar(v: number | null | undefined): string {
  if (v == null) return '—';
  if (Math.abs(v) >= 1_000_000) return '$' + (v / 1_000_000).toFixed(2) + 'M';
  if (Math.abs(v) >= 1_000) return '$' + (v / 1_000).toFixed(1) + 'K';
  return '$' + v.toFixed(2);
}

/** Alias for fmtNum — used in table components that named it `formatNumber`. */
export const formatNumber = fmtNum;

/** Format an integer, returning '—' for nullish or zero. */
export function formatInt(v: number | null | undefined): string {
  if (v == null || v === 0) return '—';
  return v.toLocaleString('en-US');
}

// ─── Side class ──────────────────────────────────────────────────────────────

/** Return the CSS class for a BUY/SELL side indicator. */
export function getSideClass(side: string): string {
  return side === 'BUY' ? 'side-buy' : side === 'SELL' ? 'side-sell' : '';
}
