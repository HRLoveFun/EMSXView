import { describe, expect, it } from 'vitest';

import type { Order } from '@execution/types';
import { normalizeTime, resolveEquTicker, resolveInterval, toChartData } from './interval-series';

const makeOrder = (overrides: Partial<Order> = {}): Order =>
  ({
    id: '1',
    symbol: 'AAPL',
    exchange: 'US',
    createdAt: '2026-04-08T09:31:00',
    strategyStartTime: '',
    strategyEndTime: '',
    ...overrides,
  }) as Order;

describe('normalizeTime', () => {
  it.each([
    ['09:30', '09:30:00'],
    ['09:30:15', '09:30:15'],
    ['0930', '09:30:00'],
    ['093015', '09:30:15'],
    ['9:30', '09:30:00'],
  ])('normalizes %s to %s', (input, expected) => {
    expect(normalizeTime(input)).toBe(expected);
  });

  it('returns null for invalid input', () => {
    expect(normalizeTime('')).toBeNull();
    expect(normalizeTime('25:00')).toBeNull();
    expect(normalizeTime('abc')).toBeNull();
  });
});

describe('resolveEquTicker', () => {
  it('builds the BDIB composite code', () => {
    expect(resolveEquTicker(makeOrder())).toBe('AAPL US Equity');
  });

  it('keeps an existing composite code', () => {
    expect(resolveEquTicker(makeOrder({ symbol: 'AAPL US Equity' }))).toBe('AAPL US Equity');
  });
});

describe('resolveInterval', () => {
  const now = new Date('2026-04-09T10:00:00');

  it('uses strategy start/end when present', () => {
    const resolved = resolveInterval(
      makeOrder({ strategyStartTime: '09:30', strategyEndTime: '16:00' }),
      now,
    );
    expect(resolved).toEqual({
      tradeDate: '20260408',
      start: '09:30:00',
      end: '16:00:00',
      endAssumed: false,
    });
  });

  it('falls back to close when end is missing on a past date', () => {
    const resolved = resolveInterval(makeOrder({ strategyStartTime: '09:30' }), now);
    expect(resolved.end).toBe('16:00:00');
    expect(resolved.endAssumed).toBe(true);
  });
});

describe('toChartData', () => {
  it('keeps gaps as null price instead of interpolating', () => {
    const data = toChartData([
      {
        bucket_start: '09:30:00',
        bucket_end: '09:31:00',
        price: 100,
        vwap: 100,
        volume: 10,
        cum_volume: 10,
        is_gap: false,
      },
      {
        bucket_start: '09:31:00',
        bucket_end: '09:32:00',
        price: null,
        vwap: null,
        volume: 0,
        cum_volume: 10,
        is_gap: true,
      },
    ]);
    expect(data[0]).toMatchObject({ time: '09:30', price: 100, cumVolume: 10 });
    expect(data[1]).toMatchObject({ time: '09:31', price: null, isGap: true });
  });
});
