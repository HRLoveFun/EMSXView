import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OrderAggregateTable } from '../components/OrderAggregateTable';
import type { TcaOrderReport } from '../services/api';

// ── 测试数据 ──

const orderReport: TcaOrderReport = {
  filters: { aggregation: 'aggregated', limit: 200, offset: 0 },
  total_orders: 2,
  offset: 0,
  limit: 200,
  generated_at: '2026-08-17T00:00:00Z',
  orders: [
    {
      order_id: 'O1',
      order_as_of_date: '20260812',
      equ_ticker: 'AAPL US Equity',
      exchange: 'US',
      side: 'BUY',
      broker: 'BROKER-A',
      algo: 'VWAP',
      trader_name: 'Trader',
      route_count: 2,
      fill_count: 10,
      delay_cost: 0,
      trading_cost: 2000,
      opportunity_cost: 1000,
      wagner_is: 3000,
      p_arrival: 10.0,
      p_decision: 10.0,
      p_close: 11.0,
      arrival_cost_bps: -20.0,
      close_cost_bps: 40.0,
      wagner_is_bps: 30.0,
      temp_impact_5min_bps: 12.5,
      temp_impact_10min_bps: 10.0,
      temp_impact_30min_bps: 8.0,
      perm_impact_bps: 50.0,
      fill: 4000,
      route_shares: 5000,
      par_rate: 0.8,
      cost_stddev: 3.5,
      cost_p95: 6.0,
      cost_cvar: 7.2,
      order_duration_sec: 1800,
      exec_rate_shares_per_min: 133.3,
      recovery_truncated: 0,
    },
    {
      order_id: 'O2',
      order_as_of_date: '20260812',
      equ_ticker: 'MSFT US Equity',
      exchange: 'US',
      side: 'SELL',
      broker: 'BROKER-B',
      algo: 'TWAP',
      trader_name: 'Trader',
      route_count: 1,
      fill_count: 3,
      delay_cost: null,
      trading_cost: null,
      opportunity_cost: null,
      wagner_is: null,
      p_arrival: null,
      p_decision: null,
      p_close: null,
      arrival_cost_bps: null,
      close_cost_bps: null,
      wagner_is_bps: null,
      temp_impact_5min_bps: null,
      temp_impact_10min_bps: null,
      temp_impact_30min_bps: null,
      perm_impact_bps: null,
      fill: null,
      route_shares: null,
      par_rate: null,
      cost_stddev: null,
      cost_p95: null,
      cost_cvar: null,
      order_duration_sec: null,
      exec_rate_shares_per_min: null,
      recovery_truncated: null,
    },
  ],
};

describe('OrderAggregateTable', () => {
  it('renders aggregated order rows with computed metrics', () => {
    render(<OrderAggregateTable report={orderReport} error={null} isLoading={false} />);

    // 订单标识
    expect(screen.getByText('O1')).toBeTruthy();
    expect(screen.getByText('O2')).toBeTruthy();
    // 聚合值：Wagner IS (SUM) = 3000 → 3.0K
    expect(screen.getByText('+3.0K')).toBeTruthy();
    // 到达价成本（加权）-20 bps
    expect(screen.getByText('-20.0 bps')).toBeTruthy();
    // 成本标准差
    expect(screen.getByText('3.5 bps')).toBeTruthy();
    // 执行历时 1800s → 30m0s
    expect(screen.getByText('30m0s')).toBeTruthy();
    // 暂时冲击
    expect(screen.getByText('+12.5 bps')).toBeTruthy();
  });

  it('renders placeholder for missing values', () => {
    render(<OrderAggregateTable report={orderReport} error={null} isLoading={false} />);

    // O2 全部指标为 null → 显示 —（多行都有 —，检查至少存在）
    const placeholders = screen.getAllByText('—');
    expect(placeholders.length).toBeGreaterThan(0);
  });

  it('shows error alert when error is set', () => {
    render(<OrderAggregateTable report={null} error="boom" isLoading={false} />);
    expect(screen.getByText('Order aggregation failed')).toBeTruthy();
    expect(screen.getByText('boom')).toBeTruthy();
  });

  it('shows loading placeholder while loading', () => {
    render(<OrderAggregateTable report={null} error={null} isLoading />);
    expect(screen.getByText('Loading order aggregate view…')).toBeTruthy();
  });

  it('shows empty state when no orders', () => {
    render(<OrderAggregateTable report={null} error={null} isLoading={false} />);
    expect(screen.getByText('No orders matched the current filters.')).toBeTruthy();
  });
});
