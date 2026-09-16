import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  loadConditions,
  saveConditions,
  matchesAnyCondition,
  getOrderFlags,
  DEFAULT_CONDITIONS,
  CONDITION_DEFS,
} from './monitor-conditions';
import type { MonitorConditions } from './monitor-conditions';
import type { Order } from '@execution/types';

function createOrder(overrides?: Partial<Order>): Order {
  return {
    id: '1',
    symbol: 'AAPL',
    side: 'BUY',
    status: 'WORKING',
    orderType: 'LIMIT',
    quantity: 1000,
    filledQuantity: 200,
    remainingQuantity: 800,
    price: 150,
    avgPrice: 149.5,
    dollarValueUsd: null,
    pctChange: null,
    adv5d: null,
    isOddLot: false,
    createdAt: '2024-01-01T10:00:00Z',
    updatedAt: '2024-01-01T10:00:00Z',
    account: 'ACC1',
    portfolio: 'PORT1',
    trader: 'TRADER1',
    exchange: 'US',
    currency: 'USD',
    timeInForce: 'DAY',
    percentFilled: 20,
    stopPrice: undefined,
    notes: '',
    customNote1: '',
    customNote2: '',
    customNote3: '',
    customNote4: '',
    customNote5: '',
    traderNotes: '',
    execInstruction: '',
    strategyType: '',
    strategyStyle: '',
    strategyPartRate: null,
    strategyStartTime: '',
    strategyEndTime: '',
    broker: '',
    fxRate: null,
    arrivalPrice: null,
    lastPrice: null,
    dayAvgPrice: null,
    mktVwap: null,
    percentRemain: null,
    ...overrides,
  };
}

describe('loadConditions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns deep-cloned defaults when storage is empty', () => {
    const result = loadConditions();
    expect(result).toEqual(DEFAULT_CONDITIONS);
    expect(result).not.toBe(DEFAULT_CONDITIONS);
  });

  it('returns deep-cloned defaults when storage is corrupted JSON', () => {
    localStorage.setItem('emsx-monitor-conditions', '{broken');
    const result = loadConditions();
    expect(result).toEqual(DEFAULT_CONDITIONS);
  });

  it('merges stored partial config with defaults', () => {
    localStorage.setItem(
      'emsx-monitor-conditions',
      JSON.stringify({ dollarValueLow: { enabled: false, threshold: 5000 } }),
    );
    const result = loadConditions();
    expect(result.dollarValueLow.enabled).toBe(false);
    expect(result.dollarValueLow.threshold).toBe(5000);
    expect(result.dollarValueHigh.enabled).toBe(true);
    expect(result.dollarValueHigh.threshold).toBe(49_000_000);
  });
});

describe('saveConditions', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('persists conditions to localStorage', () => {
    const modified = { ...DEFAULT_CONDITIONS, dollarValueLow: { enabled: false, threshold: 1000 } };
    saveConditions(modified);
    const raw = localStorage.getItem('emsx-monitor-conditions');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.dollarValueLow.threshold).toBe(1000);
  });

  it('does not throw when localStorage is full', () => {
    const setItem = localStorage.setItem;
    localStorage.setItem = vi.fn(() => { throw new Error('QuotaExceeded'); });
    expect(() => saveConditions(DEFAULT_CONDITIONS)).not.toThrow();
    localStorage.setItem = setItem;
  });
});

describe('matchesAnyCondition', () => {
  const allDisabled: MonitorConditions = {
    dollarValueLow: { enabled: false, threshold: 10000 },
    dollarValueHigh: { enabled: false, threshold: 49000000 },
    pctChangeBuy: { enabled: false, threshold: 4.5 },
    pctChangeSell: { enabled: false, threshold: 4.5 },
    qtyAdvRatio: { enabled: false, threshold: 5 },
    oddLot: { enabled: false, value: true },
    lazy: { enabled: false, value: true },
  };

  it('returns false when no conditions are enabled', () => {
    expect(matchesAnyCondition(createOrder(), allDisabled)).toBe(false);
  });

  it('matches dollarValueLow', () => {
    const conditions: MonitorConditions = { ...allDisabled, dollarValueLow: { enabled: true, threshold: 100000 } };
    expect(matchesAnyCondition(createOrder({ dollarValueUsd: 50000 }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ dollarValueUsd: 150000 }), conditions)).toBe(false);
  });

  it('matches dollarValueHigh', () => {
    const conditions: MonitorConditions = { ...allDisabled, dollarValueHigh: { enabled: true, threshold: 100000 } };
    expect(matchesAnyCondition(createOrder({ dollarValueUsd: 150000 }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ dollarValueUsd: 50000 }), conditions)).toBe(false);
  });

  it('matches pctChangeBuy for BUY orders', () => {
    const conditions: MonitorConditions = { ...allDisabled, pctChangeBuy: { enabled: true, threshold: 2.0 } };
    expect(matchesAnyCondition(createOrder({ side: 'BUY', pctChange: 3.0 }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ side: 'BUY', pctChange: 1.0 }), conditions)).toBe(false);
    expect(matchesAnyCondition(createOrder({ side: 'SELL', pctChange: 10.0 }), conditions)).toBe(false);
  });

  it('matches pctChangeSell for SELL orders (negative)', () => {
    const conditions: MonitorConditions = { ...allDisabled, pctChangeSell: { enabled: true, threshold: 2.0 } };
    expect(matchesAnyCondition(createOrder({ side: 'SELL', pctChange: -3.0 }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ side: 'SELL', pctChange: -1.0 }), conditions)).toBe(false);
    expect(matchesAnyCondition(createOrder({ side: 'BUY', pctChange: -5.0 }), conditions)).toBe(false);
  });

  it('matches qtyAdvRatio', () => {
    const conditions: MonitorConditions = { ...allDisabled, qtyAdvRatio: { enabled: true, threshold: 2.0 } };
    expect(matchesAnyCondition(createOrder({ quantity: 1000, adv5d: 20000 }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ quantity: 100, adv5d: 20000 }), conditions)).toBe(false);
  });

  it('matches oddLot (isOddLot === true)', () => {
    const conditions: MonitorConditions = { ...allDisabled, oddLot: { enabled: true, value: true } };
    expect(matchesAnyCondition(createOrder({ isOddLot: true }), conditions)).toBe(true);
    expect(matchesAnyCondition(createOrder({ isOddLot: false }), conditions)).toBe(false);
  });

  it('returns false when order has null values for the condition field', () => {
    const conditions: MonitorConditions = { ...allDisabled, pctChangeBuy: { enabled: true, threshold: 1.0 } };
    expect(matchesAnyCondition(createOrder({ side: 'BUY', pctChange: null }), conditions)).toBe(false);
  });
});

describe('getOrderFlags', () => {
  const allEnabled = {
    dollarValueLow: { enabled: true, threshold: 100000 },
    dollarValueHigh: { enabled: true, threshold: 49000000 },
    pctChangeBuy: { enabled: true, threshold: 4.5 },
    pctChangeSell: { enabled: true, threshold: 4.5 },
    qtyAdvRatio: { enabled: true, threshold: 5 },
    oddLot: { enabled: true, value: true },
    lazy: { enabled: true, value: true },
  };

  it('returns flags for all matched conditions', () => {
    const order = createOrder({ dollarValueUsd: 50000, isOddLot: true });
    const flags = getOrderFlags(order, allEnabled);
    expect(flags.length).toBeGreaterThanOrEqual(2);
    expect(flags.some(f => f.label.includes('$Value'))).toBe(true);
    expect(flags.some(f => f.label.includes('Odd Lot'))).toBe(true);
  });

  it('returns empty array when no condition matches', () => {
    const order = createOrder({ dollarValueUsd: 500000, isOddLot: false });
    const flags = getOrderFlags(order, {
      ...allEnabled,
      dollarValueLow: { enabled: false, threshold: 100000 },
      oddLot: { enabled: false, value: true },
    });
    expect(flags.length).toBe(0);
  });
});

describe('CONDITION_DEFS', () => {
  it('has 6 condition definitions', () => {
    expect(CONDITION_DEFS).toHaveLength(6);
  });

  it('each definition has required fields', () => {
    for (const def of CONDITION_DEFS) {
      expect(def.id).toBeTruthy();
      expect(def.label).toBeTruthy();
      expect(typeof def.test).toBe('function');
      expect(typeof def.groupLabel).toBe('function');
    }
  });

  it('oddLot is the only boolean condition', () => {
    const boolDefs = CONDITION_DEFS.filter(d => d.isBool);
    expect(boolDefs).toHaveLength(1);
    expect(boolDefs[0].id).toBe('oddLot');
  });
});
