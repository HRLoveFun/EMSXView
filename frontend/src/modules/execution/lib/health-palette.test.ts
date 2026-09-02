import { describe, it, expect } from 'vitest';
import {
  getOrderHealth,
  getRouteHealth,
  isLazyOrder,
  computeIdleShare,
  computeIdleShareByOrder,
  maxHealth,
  compareHealth,
  HEALTH_RANK,
  HEALTH_PALETTE,
} from './health-palette';
import { DEFAULT_CONDITIONS } from './monitor-conditions';
import type { HealthLevel } from './health-palette';
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
  const pendingRoute = (overrides?: Partial<Route>): Route =>
    createRoute({ status: 'WORKING', ...overrides });

  it('returns 0 when routes is undefined or empty', () => {
    expect(computeIdleShare(createOrder(), undefined)).toBe(0);
    expect(computeIdleShare(createOrder(), [])).toBe(0);
  });

  it('computes positive idle share (remaining − pending working)', () => {
    const order = createOrder({ quantity: 100, filledQuantity: 0, remainingQuantity: 100 });
    const routes = [
      pendingRoute({ id: 'r1', routeId: 1, sequence: 1, amount: 30, working: 30 }),
      pendingRoute({ id: 'r2', routeId: 2, sequence: 1, amount: 20, working: 20 }),
    ];
    expect(computeIdleShare(order, routes)).toBe(50);
  });

  it('已成交部分不计入可路由额度（基数取剩余量而非总量）', () => {
    // 总量 1000、已成交 600 → 剩余 400；在途 100 → idle 应为 300
    const order = createOrder({
      quantity: 1000, filledQuantity: 600, remainingQuantity: 400,
    });
    const routes = [pendingRoute({ sequence: 1, amount: 100, working: 100 })];
    expect(computeIdleShare(order, routes)).toBe(300);
  });

  it('终态路由不占用额度，只扣在途量', () => {
    const order = createOrder({ quantity: 1000, filledQuantity: 0, remainingQuantity: 1000 });
    const routes = [
      createRoute({ id: 'r1', sequence: 1, status: 'FILLED', amount: 200, working: 0 }),
      pendingRoute({ id: 'r2', sequence: 1, amount: 300, working: 300 }),
    ];
    expect(computeIdleShare(order, routes)).toBe(700);
  });

  it('只扣 working 而非 amount（避免对已成交二次扣减）', () => {
    // 部分成交的路由：amount 500 = working 200 + filled 300
    const order = createOrder({
      quantity: 1000, filledQuantity: 300, remainingQuantity: 700,
    });
    const routes = [
      createRoute({ sequence: 1, status: 'PARTFILLED', amount: 500, working: 200 }),
    ];
    expect(computeIdleShare(order, routes)).toBe(500);
  });

  it('returns 0 when pending exceeds remaining', () => {
    const order = createOrder({ quantity: 50, filledQuantity: 0, remainingQuantity: 50 });
    const routes = [pendingRoute({ sequence: 1, amount: 60, working: 60 })];
    expect(computeIdleShare(order, routes)).toBe(0);
  });
});

describe('computeIdleShareByOrder', () => {
  it('批量计算并按父单 sequence 归集在途量', () => {
    const orders = [
      createOrder({ id: '1', quantity: 1000, filledQuantity: 200, remainingQuantity: 800 }),
      createOrder({ id: '2', quantity: 500, filledQuantity: 0, remainingQuantity: 500 }),
    ];
    const routes = [
      createRoute({ id: 'r1', sequence: 1, status: 'WORKING', amount: 300, working: 300 }),
      createRoute({ id: 'r2', sequence: 1, status: 'PARTFILLED', amount: 200, working: 100 }),
      createRoute({ id: 'r3', sequence: 2, status: 'FILLED', amount: 500, working: 0 }),
    ];
    const idle = computeIdleShareByOrder(orders, routes);
    // 单 1：800 − (300 + 100) = 400；单 2：500 − 0 = 500
    expect(idle.get('1')).toBe(400);
    expect(idle.get('2')).toBe(500);
  });
});

describe('maxHealth / compareHealth', () => {
  it('maxHealth picks higher severity', () => {
    expect(maxHealth('critical', 'warning')).toBe('critical');
    expect(maxHealth('healthy', 'info')).toBe('info');
    expect(maxHealth('warning', 'warning')).toBe('warning');
  });

  it('compareHealth sorts critical first', () => {
    const levels: HealthLevel[] = ['healthy', 'critical', 'warning', 'info'];
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
