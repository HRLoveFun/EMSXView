import { describe, expect, it } from 'vitest';
import { buildWarningOnlyPage } from './report-state';
import { createDefaultCostViewConfig } from './thresholds';
import type { CostViewFilterFormState, TcaReport, TcaRouteSummary } from '../types';

function createRoute(orderId: string, routeId: string, pnlVwap: number, fill = 95): TcaRouteSummary {
  return {
    order_id: orderId,
    route_id: routeId,
    order_as_of_date: '20260422',
    exchange: 'US',
    account: null,
    equ_ticker: 'AAPL US Equity',
    currency: 'USD',
    side: 'BUY',
    amount: 1000,
    route_shares: 1000,
    type: null,
    limit_price: null,
    stop_price: null,
    broker: 'BROKER-A',
    strategy_type: null,
    algo: 'VWAP',
    trader_name: 'Trader',
    fill,
    fill_continuous: fill,
    fill_close: fill,
    par_rate: 0.01,
    par_rate_continuous: 0.01,
    par_rate_close: 0.01,
    p_avg: 100,
    p_avg_continuous: 100,
    pnl_vwap: pnlVwap,
    pnl_vwap_continuous: pnlVwap,
    rpm: 0.3,
    rpm_continuous: 0.3,
    pwp_5: null,
    pwp_10: null,
    pwp_15: null,
    pwp_20: null,
    pwp_25: null,
    time_series: [],
  };
}

function createReport(routes: TcaRouteSummary[]): TcaReport {
  return {
    filters: {
      aggregation: 'per_order',
      limit: 50,
      offset: 0,
    },
    total_orders: routes.length,
    offset: 0,
    limit: 50,
    generated_at: '2026-04-22T09:30:00.000Z',
    orders: routes,
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
      createRoute('ORDER-1', 'ROUTE-1', 4),
      createRoute('ORDER-2', 'ROUTE-1', 14),
      createRoute('ORDER-3', 'ROUTE-1', 30),
      createRoute('ORDER-4', 'ROUTE-1', 6, 40),
      createRoute('ORDER-5', 'ROUTE-1', 8),
    ]);

    const firstPage = buildWarningOnlyPage(report, config, form, 0);
    const secondPage = buildWarningOnlyPage(report, config, form, 2);

    expect(firstPage.total_orders).toBe(3);
    expect(firstPage.orders.map((route) => route.order_id)).toEqual(['ORDER-2', 'ORDER-3']);
    expect(secondPage.total_orders).toBe(3);
    expect(secondPage.orders.map((route) => route.order_id)).toEqual(['ORDER-4']);
    expect(secondPage.offset).toBe(2);
    expect(secondPage.limit).toBe(2);
  });
});
