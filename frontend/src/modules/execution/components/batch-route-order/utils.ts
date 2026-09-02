/** Pure utility functions for batch-route-order dialog. */

import type { Order } from '@execution/types';

/**
 * 父单可路由基数 = 剩余量（remainingQuantity），**不是**总量（quantity）。
 *
 * 口径的唯一真相源在 `@execution/lib/route-capacity`，此处仅 re-export，
 * 避免 lib / components 各维护一份造成漂移。
 */
export { remainingOf } from '@execution/lib/route-capacity';

/** Lot size for an order (PX_ROUND_LOT_SIZE refdata; fallback 100 for JP, else 1). */
export function lotSizeOf(o: Order): number {
  if (o.roundLotSize && o.roundLotSize > 0) return o.roundLotSize;
  return (o.exchange ?? '').toUpperCase() === 'JP' ? 100 : 1;
}

export function floorToLot(qty: number, lot: number): number {
  if (!Number.isFinite(qty) || qty <= 0 || lot <= 0) return 0;
  return Math.floor(qty / lot) * lot;
}

/** Equally split `remaining` across `n` destinations, lot-floored.
 *  Last bucket absorbs the residual lots so ∑ == floorToLot(remaining, lot). */
export function equalSplit(remaining: number, lot: number, n: number): number[] {
  if (n <= 0) return [];
  const totalLots = Math.floor(remaining / lot);
  if (totalLots <= 0) return Array(n).fill(0);
  const baseLots = Math.floor(totalLots / n);
  const extra = totalLots - baseLots * n;
  return Array.from({ length: n }, (_, i) =>
    (baseLots + (i < extra ? 1 : 0)) * lot,
  );
}

/** Broker-specific default strategy overrides. */
const BROKER_DEFAULT_STRATEGY: Record<string, string> = {
  'EQ-BARCLAY': 'VWAP-EU',
  'EQ-CLSA': 'vwap_adp',
};

/** Pick a default strategy for a broker.
 *  Priority:
 *    1. Broker-specific override (BROKER_DEFAULT_STRATEGY), if available
 *    2. Exact `VWAP` match (normalized to alphanumerics)
 *    3. Empty string — no default, user must pick manually */
export function defaultStrategyFor(strategies: string[], broker?: string): string {
  if (strategies.length === 0) return '';

  if (broker && broker in BROKER_DEFAULT_STRATEGY) {
    const preferred = BROKER_DEFAULT_STRATEGY[broker];
    const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const normPreferred = norm(preferred);
    const match = strategies.find(s => norm(s) === normPreferred);
    if (match) return match;
  }

  const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const exact = strategies.find(s => norm(s) === 'VWAP');
  if (exact) return exact;

  return '';
}

export function clientKeyOf(orderId: string, broker: string): string {
  return `${orderId}#${broker}`;
}
