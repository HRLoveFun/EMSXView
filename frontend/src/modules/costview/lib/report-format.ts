/** CostView 报告统一格式化工具（Report 页面与 HTML 导出共用口径） */

export const formatNum = (value: number | null, digits = 2): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: digits });

export const formatMoney = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
};

export const formatShares = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
};

/** bps 值格式化（保留两位小数，None → —） */
export const formatBps = (value: number | null): string =>
  value == null || !Number.isFinite(value) ? '—' : value.toFixed(2);

/** 百分比展示（0-1 小数 → %），None → —；与后端口径一致封顶防假象 */
export const formatPct = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  let pct = value * 100.0;
  if (pct > 100.0) pct = 100.0;
  if (value < 1.0 && pct > 99.99) pct = 99.99;
  return `${pct.toFixed(2)}%`;
};

/** 风险区间展示 stddev / CVaR */
export const formatRisk = (stddev: number | null, cvar: number | null): string =>
  `${formatNum(stddev)} / ${formatNum(cvar)}`;

export const formatInt = (value: number | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  try {
    return `${Math.round(value).toLocaleString()}`;
  } catch {
    return '—';
  }
};

/** 历时展示：秒 → 分钟/小时 */
export const formatDuration = (seconds: number | null): string => {
  if (seconds == null || !Number.isFinite(seconds)) return '—';
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${(seconds / 60).toFixed(1)}m`;
  return `${seconds.toFixed(0)}s`;
};

/** 成交金额格式化（带币种前缀），None → — */
export const formatMoneyWithCcy = (value: number | null, currency: string | null): string => {
  if (value == null || !Number.isFinite(value)) return '—';
  const ccy = (currency ?? '').toUpperCase();
  const prefix = ccy ? `${ccy} ` : '';
  return `${prefix}${formatMoney(value)}`;
};
