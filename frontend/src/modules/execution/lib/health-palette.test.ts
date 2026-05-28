import { describe, it, expect } from 'vitest';
import {
  getOrderHealth,
  getRouteHealth,
  isLazyOrder,
  computeIdleShare,
  maxHealth,
  compareHealth,
  HEALTH_RANK,
  HEALTH_PALETTE,
} from './health-palette';
import { DEFAULT_CONDITIONS } from './monitor-conditions';
import type { Order, Route } from '@execution/types';

function createOrder(overrides?: Partial<Order>): Order {
  return {
    id: '1',
    symbol: 'AAPL',
    side: 'BUY',
    status: 'WORKING',
    orderType: 'LIMIT',
    quantity: 1000,
    filledQuantity: 0,
    remainingQuantity: 1000,
    price: null,
    avgPrice: null,
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
    percentFilled: 0,
    stopPrice: null,
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

describe('getOrderHealth', () => {
  it('returns critical for REJECTED status', () => {
    const health = getOrderHealth({ order: createOrder({ status: 'REJECTED' }), conditions: DEFAULT_CONDITIONS });
    expect(health).toBe('critical');
  });

  it('returns critical for PENDING_CANCEL status', () => {
    const health = getOrderHealth({ order: createOrder({ status: 'PENDING_CANCEL' }), conditions: DEFAULT_CONDITIONS });
    expect(health).toBe('critical');
  });

  it('returns warning when order matches a condition', () => {
    const order = createOrder({ dollarValueUsd: 5000 });
    const health = getOrderHealth({ order, conditions: DEFAULT_CONDITIONS });
    expect(health).toBe('warning');
  });

  it('returns healthy for a normal WORKING order within thresholds', () => {
    const order = createOrder({ dollarValueUsd: 500000 });
    const health = getOrderHealth({ order, conditions: DEFAULT_CONDITIONS });
    expect(health).toBe('healthy');
  });

  it('returns info for lazy orders', () => {
    const order = createOrder({ status: 'NEW' });
    const health = getOrderHealth({ order, conditions: DEFAULT_CONDITIONS });
    expect(health).toBe('info');
  });
});

function createRoute(overrides?: Partial<Route>): Route {
  return {
    id: '1', routeId: 1, sequence: 1, status: 'WORKING', broker: 'GS',
    amount: 100, filled: 0, working: 0, remainBalance: 100,
    avgPrice: null, limitPrice: null, stopPrice: null, lastPrice: null,
    lastShares: null, dayAvgPrice: null, dayFill: 0, orderType: 'LIMIT',
    tif: 'DAY', handInstruction: '', execInstruction: '', notes: '',
    strategyType: '', strategyStyle: '', strategyPartRate1: null,
    strategyPartRate2: null, strategyStartTime: '', strategyEndTime: '',
    exchangeDestination: '', executeBroker: '', isManualRoute: 0,
    routeRefId: '', currencyPair: '', urgencyLevel: '',
    routeCreateDate: '', routeCreateTime: '', lastFillDate: '',
    lastFillTime: '', timeStamp: '', routeLastUpdateTime: '',
    fillId: 0, percentRemain: null, reasonCode: '', reasonDesc: '',
    brokerStatus: '', settleAmount: null, settleDate: '',
    commRate: null, brokerComm: null, userCommRate: null, userFees: null,
    miscFees: null, userNetMoney: null, principal: null, routePrice: null,
    ticker: 'AAPL', side: 'BUY', portfolio: 'P1', trader: 'T1',
    traderUuid: 0, currency: 'USD', exchange: 'US',
    ...overrides,
  };
}

describe('getRouteHealth', () => {
  it('returns critical for REJECTED route', () => {
    expect(getRouteHealth(createRoute({ status: 'REJECTED' }))).toBe('critical');
  });

  it('returns healthy for FILLED route', () => {
    expect(getRouteHealth(createRoute({ status: 'FILLED', filled: 100 }))).toBe('healthy');
  });
});

describe('isLazyOrder', () => {
  it('returns true for status not in exempt set', () => {
    expect(isLazyOrder(createOrder({ status: 'NEW' }))).toBe(true);
    expect(isLazyOrder(createOrder({ status: 'REJECTED' }))).toBe(true);
  });

  it('returns false for WORKING status with no idle share', () => {
    expect(isLazyOrder(createOrder({ status: 'WORKING' }))).toBe(false);
  });

  it('returns false for SUSPENDED regardless of idle share', () => {
    const ctx = { idleShareByOrderId: new Map([['1', 100]]) };
    expect(isLazyOrder(createOrder({ status: 'SUSPENDED' }), ctx)).toBe(false);
  });

  it('returns true for exempt status with positive idle share', () => {
    const ctx = { idleShareByOrderId: new Map([['1', 50]]) };
    expect(isLazyOrder(createOrder({ status: 'FILLED', id: '1' }), ctx)).toBe(true);
  });
});

describe('computeIdleShare', () => {
  it('returns 0 when routes is undefined or empty', () => {
    expect(computeIdleShare(createOrder({ quantity: 100 }), undefined)).toBe(0);
    expect(computeIdleShare(createOrder({ quantity: 100 }), [])).toBe(0);
  });

  it('computes positive idle share', () => {
    const order = createOrder({ quantity: 100 });
    const routes = [
      createRoute({ id: 'r1', routeId: 1, sequence: 1, amount: 30 }),
      createRoute({ id: 'r2', routeId: 2, sequence: 1, amount: 20 }),
    ];
    expect(computeIdleShare(order, routes)).toBe(50);
  });

  it('returns 0 when placed exceeds quantity', () => {
    const order = createOrder({ quantity: 50 });
    const routes = [
      createRoute({ id: 'r1', routeId: 1, sequence: 1, amount: 60 }),
    ];
    expect(computeIdleShare(order, routes)).toBe(0);
  });
});

describe('maxHealth / compareHealth', () => {
  it('maxHealth picks higher severity', () => {
    expect(maxHealth('critical', 'warning')).toBe('critical');
    expect(maxHealth('healthy', 'info')).toBe('info');
    expect(maxHealth('warning', 'warning')).toBe('warning');
  });

  it('compareHealth sorts critical first', () => {
    const levels = ['healthy', 'critical', 'warning', 'info'];
    levels.sort(compareHealth);
    expect(levels).toEqual(['critical', 'warning', 'info', 'healthy']);
  });
});

describe('HEALTH_RANK', () => {
  it('has correct ranking order', () => {
    expect(HEALTH_RANK.critical).toBeGreaterThan(HEALTH_RANK.warning);
    expect(HEALTH_RANK.warning).toBeGreaterThan(HEALTH_RANK.info);
    expect(HEALTH_RANK.info).toBeGreaterThan(HEALTH_RANK.healthy);
  });
});

describe('HEALTH_PALETTE', () => {
  it('has all four levels defined', () => {
    for (const level of ['critical', 'warning', 'info', 'healthy'] as const) {
      expect(HEALTH_PALETTE[level].label).toBeTruthy();
      expect(HEALTH_PALETTE[level].stripClass).toBeTruthy();
    }
  });
});
