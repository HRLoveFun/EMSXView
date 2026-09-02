import type {
  MarketAlertSeverity,
  MarketCandidatePayload,
  MarketSnapshotPayload,
  MarketSnapshotRow,
} from '../types';

// 后端 trade_date 约定为 YYYYMMDD；HTML date input 约定为 YYYY-MM-DD。
// 以下两个函数负责双向转换，非法输入一律降级为空值。

export function buildMarketCandidatePayload(
  snapshot: MarketSnapshotPayload,
  selectedTickers: string[],
): MarketCandidatePayload {
  if (!selectedTickers.length) {
    return snapshot.candidate_payload;
  }

  const selected = new Set(selectedTickers);
  const candidates = snapshot.candidate_payload.candidates.filter((candidate) => selected.has(candidate.equ_ticker));

  return {
    ...snapshot.candidate_payload,
    row_count: candidates.length,
    candidates,
  };
}

export function countRowsWithSeverity(
  rows: MarketSnapshotRow[],
  severity: Extract<MarketAlertSeverity, 'warning' | 'critical'>,
): number {
  return rows.filter(
    (row) => row.liquidity_alert === severity || row.volatility_alert === severity,
  ).length;
}

// 将后端 YYYYMMDD 日期转换为 date input 可用的 YYYY-MM-DD
export function toISODateInput(value: string | undefined | null): string {
  if (!value || !/^\d{8}$/.test(value)) {
    return '';
  }
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

// 将 date input 的 YYYY-MM-DD 转换为后端 YYYYMMDD；空串返回 undefined 以清除筛选
export function fromISODateInput(value: string): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return undefined;
  }
  return value.replaceAll('-', '');
}