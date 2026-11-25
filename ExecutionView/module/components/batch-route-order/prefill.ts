/**
 * DL-25/219: derive a batch-route prefill from shadow decisions.
 *
 * Pure function: no IO. The hook fetches `GET /api/routing-decisions?order_id=`
 * for the selected orders, then this function aggregates candidate quantities
 * into broker ratios (normalised to 100), the most common strategy per broker,
 * a params hint, and the decision id per order.
 *
 * Read-only: the trader still reviews and confirms every destination.
 */

import type { ShadowDecisionRecord } from '@execution/types';

export interface PrefillResult {
  brokers: string[];
  ratios: Record<string, number>;
  strategies: Record<string, string>;
  paramsByBroker: Record<string, Record<string, unknown>>;
  decisionIds: Record<string, string>;
  rationales: string[];
  ordersWithDecision: number;
  ordersWithoutDecision: number;
}

function strategyFromParams(params?: Record<string, unknown>): string {
  if (!params) return '';
  for (const key of ['StrategyType', 'strategy_type', 'strategy', 'Strategy', 'algo']) {
    const value = params[key];
    if (typeof value === 'string' && value.trim()) return value.trim().toUpperCase();
  }
  return '';
}

export function derivePrefill(
  recordsByOrder: Record<string, ShadowDecisionRecord | null>,
): PrefillResult {
  const quantities = new Map<string, number>();
  const strategyVotes = new Map<string, Map<string, number>>();
  const paramsByBroker: Record<string, Record<string, unknown>> = {};
  const decisionIds: Record<string, string> = {};
  const rationales: string[] = [];
  let ordersWithDecision = 0;
  let ordersWithoutDecision = 0;

  for (const [orderId, record] of Object.entries(recordsByOrder)) {
    const candidates = record?.payload?.candidates ?? [];
    if (!record || candidates.length === 0) {
      ordersWithoutDecision += 1;
      continue;
    }
    ordersWithDecision += 1;
    decisionIds[orderId] = record.decision_id;
    const rationale = record.payload.rationale || record.payload.intent || '';
    if (rationale) rationales.push(`${orderId}: ${rationale}`);

    for (const candidate of candidates) {
      const broker = String(candidate.broker || '').trim();
      if (!broker) continue;
      const quantity = Number(candidate.quantity || 0);
      quantities.set(broker, (quantities.get(broker) ?? 0) + (Number.isFinite(quantity) ? quantity : 0));
      if (!paramsByBroker[broker] && candidate.strategy_params) {
        paramsByBroker[broker] = { ...candidate.strategy_params };
      }
      const strategy = strategyFromParams(candidate.strategy_params);
      if (strategy) {
        const votes = strategyVotes.get(broker) ?? new Map<string, number>();
        votes.set(strategy, (votes.get(strategy) ?? 0) + 1);
        strategyVotes.set(broker, votes);
      }
    }
  }

  const brokers = [...quantities.entries()]
    .filter(([, quantity]) => quantity > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([broker]) => broker);
  const total = brokers.reduce((sum, broker) => sum + (quantities.get(broker) ?? 0), 0);

  const ratios: Record<string, number> = {};
  if (total > 0) {
    let assigned = 0;
    brokers.forEach((broker, index) => {
      if (index === brokers.length - 1) {
        ratios[broker] = Math.max(0, 100 - assigned);
      } else {
        const quantity = quantities.get(broker) ?? 0;
        const ratio = Math.round((quantity / total) * 100);
        ratios[broker] = ratio;
        assigned += ratio;
      }
    });
    // Keep every selected broker non-zero: the dialog's ratio reconciliation
    // resets all-zero selections to an equal split, which would discard the prefill.
    for (const broker of brokers) {
      if ((ratios[broker] ?? 0) < 1) ratios[broker] = 1;
    }
    const sum = Object.values(ratios).reduce((totalRatio, value) => totalRatio + value, 0);
    if (sum !== 100 && brokers.length > 0) {
      const largest = brokers.reduce(
        (best, broker) => ((ratios[broker] ?? 0) > (ratios[best] ?? 0) ? broker : best),
        brokers[0],
      );
      ratios[largest] = Math.max(1, (ratios[largest] ?? 0) + (100 - sum));
    }
  }

  const strategies: Record<string, string> = {};
  for (const [broker, votes] of strategyVotes.entries()) {
    const [strategy] = [...votes.entries()].sort(
      (left, right) => right[1] - left[1] || left[0].localeCompare(right[0]),
    )[0];
    strategies[broker] = strategy;
  }

  return {
    brokers,
    ratios,
    strategies,
    paramsByBroker,
    decisionIds,
    rationales,
    ordersWithDecision,
    ordersWithoutDecision,
  };
}
