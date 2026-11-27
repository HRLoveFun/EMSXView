import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ExecutionBriefView } from '../components/brief/ExecutionBriefView';
import type { ExecutionBriefPayload } from '../types';

vi.mock('../services/api', () => ({
  fetchExecutionBrief: vi.fn(),
  fetchTraderFilterOptions: vi.fn(),
}));

import { fetchExecutionBrief, fetchTraderFilterOptions } from '../services/api';

const mockFetchBrief = vi.mocked(fetchExecutionBrief);
const mockFetchOptions = vi.mocked(fetchTraderFilterOptions);

const block = {
  orders: 2,
  route_count: 3,
  order_shares: 2500,
  fill_shares: 900,
  order_notional_usd: 220000,
  fill_notional_usd: 90000,
  unfilled_notional_usd: 130000,
  completion: 0.36,
  arrival_cost_bps: -11.5,
  wagner_is_bps: -18.0,
  pnl_vwap: -7.5,
  opportunity_cost_usd: -60,
  delay_cost_usd: -25,
  trading_cost_usd: -38,
};

const brief: ExecutionBriefPayload = {
  spec_version: '2026.11.27',
  generated_at: '2026-11-27T08:00:00',
  period: {
    start_date: '20261126', end_date: '20261126',
    preset: 'day', label: '每日', as_of_date: '20261126',
  },
  filters: { trader: [], ticker: [], exchange: [], side: [], strategy_type: [], algo: [], broker: [] },
  coverage: {
    orders: 2, symbols: 2, traders: 1, exchanges: ['US'], route_count: 3,
    fill_notional_usd: 90000, order_notional_usd: 220000,
    fx_missing_orders: 0, order_notional_unpriced_orders: 0, unpriced_routes: 0,
  },
  overview: { ...block, zero_fill_orders: 1 },
  sides: {
    buy: block,
    sell: { ...block, orders: 0, completion: null, arrival_cost_bps: null },
    other: { ...block, orders: 0 },
    mixed_orders: 0,
  },
  completion_buckets: [
    { key: 'complete', label: '完全成交', orders: 0, order_shares: 0, fill_shares: 0,
      order_notional_usd: 0, completion: null, share_of_orders: 0, share_of_notional: 0 },
    { key: 'overfill', label: '超成交（数据矛盾）', orders: 0, order_shares: 0, fill_shares: 0,
      order_notional_usd: 0, completion: null, share_of_orders: 0, share_of_notional: 0 },
    { key: 'partial', label: '部分成交', orders: 1, order_shares: 1500, fill_shares: 900,
      order_notional_usd: 120000, completion: 0.6, share_of_orders: 0.5, share_of_notional: 0.55 },
    { key: 'zero', label: '零成交', orders: 1, order_shares: 1000, fill_shares: 0,
      order_notional_usd: 100000, completion: 0, share_of_orders: 0.5, share_of_notional: 0.45 },
  ],
  strategy_mix: [
    { key: 'VWAP', label: 'VWAP', orders: 2, route_count: 3,
      order_notional_usd: 220000, fill_notional_usd: 90000, completion: 0.36,
      arrival_cost_bps: -11.5, wagner_is_bps: -18, opportunity_cost_usd: -60, share_of_orders: 1 },
  ],
  algo_mix: [
    { key: 'vwap', label: 'vwap', orders: 2, route_count: 3,
      order_notional_usd: 220000, fill_notional_usd: 90000, completion: 0.36,
      arrival_cost_bps: -11.5, wagner_is_bps: -18, opportunity_cost_usd: -60, share_of_orders: 1 },
  ],
  broker_mix: [
    { key: 'BROKER_A', label: 'BROKER_A', orders: 2, route_count: 3,
      order_notional_usd: 220000, fill_notional_usd: 90000, completion: 0.36,
      arrival_cost_bps: -11.5, wagner_is_bps: -18, opportunity_cost_usd: -60, share_of_orders: 1 },
  ],
  top_traders: [
    { key: 'HRCHEN', label: 'HRCHEN', orders: 2, route_count: 3,
      order_notional_usd: 220000, fill_notional_usd: 90000, completion: 0.36,
      arrival_cost_bps: -11.5, wagner_is_bps: -18, opportunity_cost_usd: -60, share_of_orders: 1 },
  ],
  top_orders: {
    by_arrival: [{
      order_id: 'O1', order_as_of_date: '20261126', ticker: 'AAPL US Equity',
      exchange: 'US', side: 'BUY', strategy_type: 'VWAP', algo: 'vwap', broker: 'BROKER_A',
      trader_name: 'HRCHEN', route_count: 2, order_shares: 1500, fill_shares: 900,
      completion: 0.6, vwap: null, arrival_cost_bps: -12, wagner_is_bps: -20,
      pnl_vwap: -8, order_notional_usd: 120000, fill_notional_usd: 90000,
      unfilled_shares: 600, unfilled_notional_usd: 30000, opportunity_cost_usd: -20,
    }],
    by_unfilled: [{
      order_id: 'O2', order_as_of_date: '20261126', ticker: 'MSFT US Equity',
      exchange: 'US', side: 'BUY', strategy_type: 'VWAP', algo: 'vwap', broker: 'BROKER_A',
      trader_name: 'HRCHEN', route_count: 1, order_shares: 1000, fill_shares: 0,
      completion: 0, vwap: null, arrival_cost_bps: null, wagner_is_bps: null,
      pnl_vwap: null, order_notional_usd: 100000, fill_notional_usd: 0,
      unfilled_shares: 1000, unfilled_notional_usd: 100000, opportunity_cost_usd: -40,
    }],
    by_opportunity: [],
  },
  anomaly: {
    orders_total: 1, critical: 1, warning: 0, rule_orders: 1, quality_orders: 0,
    by_rule: [{ key: 'fill_pct', label: 'Fill Rate', count: 1, critical: 1 }],
    top_orders: [{
      order_id: 'O2', order_as_of_date: '20261126', ticker: 'MSFT US Equity',
      side: 'BUY', severity: 'critical',
      reasons: [{ key: 'fill_pct', label: 'Fill Rate', severity: 'critical', value: 0, unit: 'percent' }],
    }],
    scope: 'order-level', note: '订单级口径',
  },
  data_availability: [
    { key: 'portfolio', label: '组合 / 账户维度', status: 'unavailable', reason: '无 Portfolio 列' },
    { key: 'fx', label: 'USD 换算', status: 'partial', reason: '非 USD 缺汇率时不计入' },
  ],
  notes: ['成本符号：负 = 不利。'],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockFetchOptions.mockResolvedValue({
    traders: ['HRCHEN'], strategy_types: ['VWAP'], symbols: ['AAPL US Equity'],
    brokers: ['BROKER_A'], algos: ['vwap'], exchanges: ['US'],
  });
  mockFetchBrief.mockResolvedValue(brief);
});

describe('ExecutionBriefView', () => {
  it('渲染 KPI、买卖拆分、完成分桶与数据缺口', async () => {
    render(<ExecutionBriefView />);

    await waitFor(() => expect(screen.getByText('订单数')).toBeInTheDocument());
    expect(screen.getByText('委托金额（USD）')).toBeInTheDocument();
    expect(screen.getByText('买卖拆分')).toBeInTheDocument();
    expect(screen.getByText('完成状态分桶')).toBeInTheDocument();
    expect(screen.getByText('零成交')).toBeInTheDocument();
    expect(screen.getByText('组合 / 账户维度')).toBeInTheDocument();
    expect(screen.getByText('未覆盖')).toBeInTheDocument();
    expect(mockFetchBrief).toHaveBeenCalledWith(
      expect.objectContaining({ preset: 'day' }),
    );
  });

  it('相对期间切换后立即按新预设取数', async () => {
    render(<ExecutionBriefView />);
    await waitFor(() => expect(screen.getByText('订单数')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: '每周' }));

    await waitFor(() => expect(mockFetchBrief).toHaveBeenLastCalledWith(
      expect.objectContaining({ preset: 'week' }),
    ));
  });

  it('自定义期间缺日期时不发请求并提示', async () => {
    render(<ExecutionBriefView />);
    await waitFor(() => expect(screen.getByText('订单数')).toBeInTheDocument());
    const callsBefore = mockFetchBrief.mock.calls.length;

    fireEvent.click(screen.getByRole('button', { name: '自定义' }));
    fireEvent.click(screen.getByRole('button', { name: '生成简报' }));

    expect(screen.getByText('筛选条件不完整')).toBeInTheDocument();
    expect(mockFetchBrief).toHaveBeenCalledTimes(callsBefore);
  });
});
