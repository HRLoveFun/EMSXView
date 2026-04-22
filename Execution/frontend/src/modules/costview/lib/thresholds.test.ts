import { describe, expect, it } from 'vitest';
import { countAlertOrders, createDefaultCostViewConfig, evaluateThreshold, getHighestOrderSeverity } from './thresholds';
import type { TcaOrderSummary } from '../types';

function createOrder(overrides: Partial<TcaOrderSummary> = {}): TcaOrderSummary {
  return {
    order_id: 'ORDER-1',
    order_as_of_date: '20260421',
    equ_ticker: 'AAPL US Equity',
    side: 'BUY',
    algo: 'VWAP',
    start_time: '09:30:00',
    end_time: '10:00:00',
    fill_pct: 95,
    exec_price: 100.25,
    interval_vwap: 100.2,
    tracking_error_bps: 3,
    volume_pct_interval: 8,
    volume_pct_adv5: 2,
    volume_pct_adv20: 2,
    intraday_volatility: 1.5,
    price_movement_pct: 0.4,
    data_quality_warning: false,
    routes: [],
    ...overrides,
  };
}

describe('CostView thresholds', () => {
  it('evaluates absolute-above thresholds correctly', () => {
    const config = createDefaultCostViewConfig();
    const trackingRule = config.rules.tracking_error_bps;

    expect(evaluateThreshold(trackingRule, 4)).toBe('normal');
    expect(evaluateThreshold(trackingRule, 12)).toBe('warning');
    expect(evaluateThreshold(trackingRule, -30)).toBe('critical');
  });

  it('uses the highest breached rule as the order severity', () => {
    const config = createDefaultCostViewConfig();
    const order = createOrder({
      fill_pct: 42,
      tracking_error_bps: 28,
      volume_pct_adv20: 11,
    });

    expect(getHighestOrderSeverity(order, config)).toBe('critical');
  });

  it('counts only warning and critical orders as alerts', () => {
    const config = createDefaultCostViewConfig();
    const orders = [
      createOrder({ order_id: 'ORDER-1', tracking_error_bps: 4 }),
      createOrder({ order_id: 'ORDER-2', tracking_error_bps: 14 }),
      createOrder({ order_id: 'ORDER-3', fill_pct: 45 }),
    ];

    expect(countAlertOrders(orders, config)).toBe(2);
  });
});