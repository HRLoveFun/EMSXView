import { describe, expect, it } from 'vitest';
import type { ShadowDecisionRecord } from '@execution/types';
import { derivePrefill } from './prefill';

function _record(
  orderId: string,
  decisionId: string,
  candidates: Array<{ broker: string; quantity: number; params?: Record<string, unknown> }>,
): ShadowDecisionRecord {
  return {
    decision_id: decisionId,
    order_id: orderId,
    payload: {
      candidates: candidates.map(candidate => ({
        broker: candidate.broker,
        quantity: candidate.quantity,
        strategy_params: candidate.params,
      })),
      rationale: `shadow ${orderId}`,
    },
  };
}

describe('derivePrefill', () => {
  it('aggregates broker quantities into normalised ratios', () => {
    const result = derivePrefill({
      O1: _record('O1', 'D1', [
        { broker: 'A', quantity: 600, params: { StrategyType: 'VWAP' } },
        { broker: 'B', quantity: 400 },
      ]),
      O2: _record('O2', 'D2', [
        { broker: 'A', quantity: 1000, params: { StrategyType: 'VWAP' } },
      ]),
    });

    expect(result.brokers).toEqual(['A', 'B']);
    expect(result.ratios).toEqual({ A: 80, B: 20 });
    expect(result.strategies).toEqual({ A: 'VWAP' });
    expect(result.decisionIds).toEqual({ O1: 'D1', O2: 'D2' });
    expect(result.ordersWithDecision).toBe(2);
    expect(result.ordersWithoutDecision).toBe(0);
    expect(result.rationales.length).toBe(2);
  });

  it('returns an empty prefill when no decision exists', () => {
    const result = derivePrefill({ O1: null });
    expect(result.brokers).toEqual([]);
    expect(result.ratios).toEqual({});
    expect(result.ordersWithDecision).toBe(0);
    expect(result.ordersWithoutDecision).toBe(1);
  });

  it('keeps the ratio sum at 100', () => {
    const result = derivePrefill({
      O1: _record('O1', 'D1', [
        { broker: 'A', quantity: 1 },
        { broker: 'B', quantity: 1 },
        { broker: 'C', quantity: 1 },
      ]),
    });
    const sum = Object.values(result.ratios).reduce((acc, value) => acc + value, 0);
    expect(sum).toBe(100);
  });
});
