import type {
  MarketAlertSeverity,
  MarketCandidatePayload,
  MarketSnapshotPayload,
  MarketSnapshotRow,
} from '../types';

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