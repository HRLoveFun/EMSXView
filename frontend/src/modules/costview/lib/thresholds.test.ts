import { describe, expect, it } from 'vitest';
import {
  countAlertOrders,
  createDefaultCostViewConfig,
  evaluateCohortSeverity,
  evaluateThreshold,
  formatAnomalyFlag,
  getHighestOrderSeverity,
} from './thresholds';
import type { ScorecardCohortMetrics, TcaRouteSummary } from '../types';

function createRoute(overrides: Partial<TcaRouteSummary> = {}): TcaRouteSummary {
  return {
    order_id: 'ORDER-1',
    route_id: 'ROUTE-1',
    order_as_of_date: '20260421',
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
    fill_count: 5,
    // fill 为成交股数（FillShares 口径）；950/1000 = 95% 完成率
    fill: 950,
    fill_continuous: 950,
    fill_close: 950,
    par_rate: 0.02,
    par_rate_continuous: 0.02,
    par_rate_close: 0.02,
    p_avg: 100.25,
    p_avg_continuous: 100.25,
    pnl_vwap: 3,
    pnl_vwap_continuous: 3,
    rpm: 0.4,
    rpm_continuous: 0.4,
    pwp_5: null,
    pwp_10: null,
    pwp_15: null,
    pwp_20: null,
    pwp_25: null,
    time_series: [],
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

  it('uses the highest breached rule as the route severity', () => {
    const config = createDefaultCostViewConfig();
    const route = createRoute({
      fill: 42,
      pnl_vwap: 28,
      par_rate: 0.11,
    });

    expect(getHighestOrderSeverity(route, config)).toBe('critical');
  });

  it('counts only warning and critical routes as alerts', () => {
    const config = createDefaultCostViewConfig();
    const routes = [
      createRoute({ order_id: 'ORDER-1', route_id: 'ROUTE-1', pnl_vwap: 4 }),
      createRoute({ order_id: 'ORDER-2', route_id: 'ROUTE-1', pnl_vwap: 14 }),
      createRoute({ order_id: 'ORDER-3', route_id: 'ROUTE-1', fill: 45 }),
    ];

    expect(countAlertOrders(routes, config)).toBe(2);
  });
});

function createCohort(overrides: Partial<ScorecardCohortMetrics> = {}): ScorecardCohortMetrics {
  return {
    cohort_key: 'BrokerA|VWAP',
    cohort_label: 'BrokerA | VWAP',
    sample_size: 12,
    order_count: 12,
    avg_tracking_error_bps: 5,
    median_tracking_error_bps: 4,
    p95_tracking_error_bps: 9,
    stddev_tracking_error_bps: 2.1,
    avg_fill_pct: 95,
    avg_volume_pct_interval: 6,
    avg_volume_pct_adv20: 3,
    avg_daily_volatility: 1.5,
    avg_intraday_volatility: 1.1,
    avg_price_movement_pct: 0.3,
    data_quality_ratio: 0.0,
    sample_size_warning: false,
    anomaly_flags: [],
    ...overrides,
  };
}

describe('CostView scorecard helpers', () => {
  it('downgrades under-sample cohorts to warning regardless of averages', () => {
    const config = createDefaultCostViewConfig();
    const cohort = createCohort({
      sample_size: 3,
      sample_size_warning: true,
      avg_tracking_error_bps: 50,
      avg_fill_pct: 20,
    });
    expect(evaluateCohortSeverity(cohort, config)).toBe('warning');
  });

  it('escalates cohorts breaching critical thresholds', () => {
    const config = createDefaultCostViewConfig();
    const cohort = createCohort({ avg_tracking_error_bps: 40 });
    expect(evaluateCohortSeverity(cohort, config)).toBe('critical');
  });

  it('returns normal when every metric is within green zone', () => {
    const config = createDefaultCostViewConfig();
    expect(evaluateCohortSeverity(createCohort(), config)).toBe('normal');
  });

  it('formats known anomaly flags with readable labels', () => {
    expect(formatAnomalyFlag('sample_size')).toBe('Small sample');
    expect(formatAnomalyFlag('high_tracking_error')).toBe('High tracking error');
    expect(formatAnomalyFlag('tail_tracking_error')).toBe('Heavy tail (P95)');
    expect(formatAnomalyFlag('data_quality')).toBe('Data quality risk');
  });

  it('humanises unknown flags by replacing underscores', () => {
    expect(formatAnomalyFlag('mystery_flag_value')).toBe('mystery flag value');
  });
});
