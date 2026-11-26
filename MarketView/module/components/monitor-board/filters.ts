/** MonitorBoardPanel column filters and market helpers (A14/229, pure functions). */

import type { MarketAlertSeverity, MonitorRow } from '../../types';

export const severityRank = (severity: MarketAlertSeverity): number =>
  severity === 'critical' ? 2 : severity === 'warning' ? 1 : 0;

/** ticker → 交易所码（'MC EU Equity' → 'EU'）；用于市场聚合与 Exchange 列。 */
export const marketOf = (equTicker: string): string => {
  const parts = equTicker.split(' ');
  return (parts.length >= 2 ? parts[parts.length - 2] : '').toUpperCase() || '?';
};

export type FilterKey = 'exchange' | 'status' | 'liquidity' | 'volatility' | 'riskNotes';

export const FILTER_COLUMNS: FilterKey[] = [
  'exchange', 'status', 'liquidity', 'volatility', 'riskNotes',
];

export const FILTER_LABELS: Record<FilterKey, string> = {
  exchange: 'Exchange',
  status: 'Status',
  liquidity: 'Liquidity',
  volatility: 'Volatility',
  riskNotes: 'Risk notes',
};

/** 行在某列上的取值（Risk notes 为多值；无提示的行走空串占位）。 */
export const rowValues = (row: MonitorRow, key: FilterKey): string[] => {
  switch (key) {
    case 'exchange':
      return [marketOf(row.equ_ticker)];
    case 'status':
      return [row.market_status];
    case 'liquidity':
      return [row.liquidity];
    case 'volatility':
      return [row.volatility];
    case 'riskNotes':
      return row.risk_notes.length ? row.risk_notes : [''];
  }
};

export const valueLabel = (value: string): string => (value === '' ? '(none)' : value);

export const uniqueValues = (rows: MonitorRow[], key: FilterKey): string[] =>
  Array.from(new Set(rows.flatMap((row) => rowValues(row, key)))).sort((a, b) =>
    valueLabel(a).localeCompare(valueLabel(b)),
  );

export type FilterState = Partial<Record<FilterKey, string[]>>;

/** 生效选择：未设置 = 全选。 */
export const effectiveSelection = (
  filters: FilterState, key: FilterKey, options: string[],
): string[] => filters[key] ?? options;

export const isFiltered = (
  filters: FilterState, key: FilterKey, options: string[],
): boolean => {
  const selection = filters[key];
  return Boolean(selection && selection.length !== options.length);
};
