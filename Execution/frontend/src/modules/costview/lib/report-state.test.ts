import { describe, expect, it } from 'vitest';
import { buildWarningOnlyPage } from './report-state';
import { createDefaultCostViewConfig } from './thresholds';
import type { CostViewFilterFormState, TcaOrderSummary, TcaReport } from '../types';

function createOrder(orderId: string, trackingErrorBps: number, fillPct = 95): TcaOrderSummary {
  return {
    order_id: orderId,
    order_as_of_date: '20260422',
    equ_ticker: 'AAPL US Equity',
    side: 'BUY',
    algo: 'VWAP',
    start_time: '09:30:00',
    end_time: '10:00:00',
    fill_pct: fillPct,
    exec_price: 100,
    interval_vwap: 100,
    tracking_error_bps: trackingErrorBps,
    volume_pct_interval: 5,
    volume_pct_adv5: 1,
    volume_pct_adv20: 1,
    intraday_volatility: 1,
    price_movement_pct: 0.3,
    data_quality_warning: false,
    routes: [],
  };
}

function createReport(orders: TcaOrderSummary[]): TcaReport {
  return {
    filters: {
      aggregation: 'per_order',
      limit: 50,
      offset: 0,
    },
    total_orders: orders.length,
    offset: 0,
    limit: 50,
    generated_at: '2026-04-22T09:30:00.000Z',
    orders,
  };
}

describe('report-state warning-only paging', () => {
  it('filters from the full backend result set before paging', () => {
    const config = createDefaultCostViewConfig();
    const form: CostViewFilterFormState = {
      orderIds: '',
      algo: '',
      startDate: '',
      endDate: '',
      broker: '',
      symbol: '',
      warningOnly: true,
      limit: 2,
    };
    const report = createReport([
      createOrder('ORDER-1', 4),
      createOrder('ORDER-2', 14),
      createOrder('ORDER-3', 30),
      createOrder('ORDER-4', 6, 40),
      createOrder('ORDER-5', 8),
    ]);

    const firstPage = buildWarningOnlyPage(report, config, form, 0);
    const secondPage = buildWarningOnlyPage(report, config, form, 2);

    expect(firstPage.total_orders).toBe(3);
    expect(firstPage.orders.map((order) => order.order_id)).toEqual(['ORDER-2', 'ORDER-3']);
    expect(secondPage.total_orders).toBe(3);
    expect(secondPage.orders.map((order) => order.order_id)).toEqual(['ORDER-4']);
    expect(secondPage.offset).toBe(2);
    expect(secondPage.limit).toBe(2);
  });
});