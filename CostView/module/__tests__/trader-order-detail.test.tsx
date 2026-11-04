import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TraderReviewView } from '../components/trader/TraderReviewView';
import type { TraderListPayload, TraderOrderDetail } from '../types';

vi.mock('../services/api', () => ({
  fetchTraderOrders: vi.fn(),
  fetchTraderFilterOptions: vi.fn(),
  fetchTraderOrderDetail: vi.fn(),
  // PR-8：peer 懒加载依赖；必须返回 Promise（返回 undefined 会让 useAsyncData 读 .then 崩）
  fetchTraderPeerStats: vi.fn(async () => null),
}));

import {
  fetchTraderFilterOptions,
  fetchTraderOrderDetail,
  fetchTraderOrders,
} from '../services/api';

const mockOrders = vi.mocked(fetchTraderOrders);
const mockOptions = vi.mocked(fetchTraderFilterOptions);
const mockDetail = vi.mocked(fetchTraderOrderDetail);

const LIST_PAYLOAD: TraderListPayload = {
  filters: { start_date: '20261020', end_date: '20261022' },
  generated_at: '2026-11-04T10:00:00',
  total_orders: 1,
  offset: 0,
  limit: 50,
  kpi: {},
  probes: { checks: [], spec_version: '2026.11.04b' },
  orders: [
    {
      order_id: '5292736', order_as_of_date: '20261022', trader_name: 'HRCHEN',
      equ_ticker: 'ABCD US Equity', exchange: 'US', side: 'BUY', strategy_type: 'VWAP',
      algo: 'vwap', broker: 'BROKER_A', route_count: 1, fill_count: 3,
      route_shares: 12000, fill: 11000, completion: 0.9167, vwap: 101.23,
      arrival_cost_bps: -4.2, opportunity_cost: -50, order_duration_sec: 600,
      fill_span_sec: 300, speed_shares_per_min: 2200, passive_ratio: 0.4,
      mixed: false, quality: { level: 'warn', flags: ['par_suspect'] },
    },
  ],
};

/** 详情 payload 工厂：默认「有 p_decision、3 笔成交、2 个桶」 */
function buildDetail(overrides: Partial<TraderOrderDetail> = {}): TraderOrderDetail {
  return {
    order: {
      ...LIST_PAYLOAD.orders[0],
      limit_price: 102.5,
      currency: 'USD',
    },
    routes: [
      {
        route_id: 'R1', broker: 'BROKER_A', algo: 'vwap',
        route_shares: 12000, fill: 11000, completion: 0.9167,
        arrival_cost_bps: -4.2, wagner_is_bps: -12.5,
      },
    ],
    fills: [
      {
        route_id: 'R1', fill_id: 'F1', ts_local: '2026-10-22T09:35:00-04:00',
        ts_sec: 35100, route_as_of_sec: 35040, price: 101.2, shares: 4000,
        is_closing_auction: false, liquidity_raw: '1', liquidity_class: 'passive',
      },
      {
        route_id: 'R1', fill_id: 'F2', ts_local: '2026-10-22T09:40:00-04:00',
        ts_sec: 35400, route_as_of_sec: 35040, price: 101.25, shares: 3000,
        is_closing_auction: false, liquidity_raw: '2', liquidity_class: 'aggressive',
      },
    ],
    timeline: {
      bucket_min: 5,
      auto_widened: false,
      buckets: [
        {
          start: '09:35', end: '09:40', fill: 4000, fill_count: 1, vwap: 101.2,
          market_volume: 20000, participation: 0.2, participation_status: 'ok',
          cum_completion: 0.3333, speed_shares_per_min: 800, accel: null,
        },
        {
          start: '09:40', end: '09:45', fill: 3000, fill_count: 1, vwap: 101.25,
          market_volume: null, participation: null, participation_status: 'unavailable',
          cum_completion: 0.5833, speed_shares_per_min: 600, accel: -200,
        },
      ],
      benchmarks: {
        p_decision: 101.0, p_arrival: 100.9, p_avg: 101.23,
        p_close: 101.5, limit_price: 102.5,
      },
      par_rate_check: { route_par_rate: 0.2, window_participation: 0.2005, ratio: 1.0025, note: null },
    },
    cost: {
      denominator: 1_212_000,
      delay_bps: -2.5, trading_bps: -6.0, opportunity_bps: -4.0,
      delay_cost: -303, trading_cost: -727, opportunity_cost: -485,
      wagner_is_bps: -12.5, residual_bps: 0.0, residual_flag: null,
      arrival_cost_bps: -4.2, opportunity_dominant: false,
      opportunity_highlight: true, note: null,
    },
    fill_stats: {
      median: 3500, p90: 3900, cv: 0.14, max_fill_ratio: 0.33,
      top3_share: 1.0, fills_per_min: 0.4,
    },
    liquidity: {
      passive_share_strict: 0.57, aggressive_share_strict: 0.43,
      auction_share: 0, unknown_share: 0, passive_cost_bps: -3.0,
      aggressive_cost_bps: -5.0, recognized_share: 1, total_shares: 7000,
      mapping: 'fix851_strict',
    },
    latency: {
      order_to_route_sec: 1.2, route_to_first_fill_sec: 60,
      order_to_first_fill_sec: 61.2, first_continuous_fill_sec: 60,
      scheduled: false, latency_anomaly: false,
    },
    daily: null,
    quality: {
      level: 'warn',
      flags: [{ id: 'par_suspect', severity: 'warn', detail: null }],
    },
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockOptions.mockResolvedValue({ traders: ['HRCHEN'], strategy_types: ['VWAP'] });
  mockOrders.mockResolvedValue(LIST_PAYLOAD);
  mockDetail.mockResolvedValue(buildDetail());
});

/** 打开详情卡（点击列表行） */
async function openDetail() {
  const user = userEvent.setup();
  render(<TraderReviewView />);
  await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());
  await user.click(screen.getByText('5292736'));
  await waitFor(() => expect(screen.getByText('订单详情')).toBeInTheDocument());
  return user;
}

describe('OrderReviewCard（210 PR-4 订单详情卡）', () => {
  it('点击列表行按订单 + 日期 + 默认 5 分钟桶取详情，并渲染三个区块', async () => {
    await openDetail();

    expect(mockDetail).toHaveBeenCalledWith({
      orderId: '5292736', orderAsOfDate: '20261022', bucketMin: 5,
    });
    // 成本分解：三分量 + 残差对账 + 分母口径
    expect(screen.getByText(/成本分解/)).toBeInTheDocument();
    expect(screen.getByText('延迟')).toBeInTheDocument();
    expect(screen.getByText('成交')).toBeInTheDocument();
    expect(screen.getByText('机会')).toBeInTheDocument();
    expect(screen.getByText(/残差/)).toBeInTheDocument();
    // 完成轨迹：5 项摘要
    expect(screen.getByText('成交跨度')).toBeInTheDocument();
    expect(screen.getByText('速度 CV（非零桶）')).toBeInTheDocument();
    expect(screen.getByText('零成交桶')).toBeInTheDocument();
    // 时间线：桶宽与不可得桶披露（收盘竞价 / 无 bar 不画 0%）
    expect(screen.getByText(/桶宽 5 分钟/)).toBeInTheDocument();
    expect(screen.getByText(/1 桶无行情/)).toBeInTheDocument();
    // 基准价 chips
    expect(screen.getByText(/决策价 101.00/)).toBeInTheDocument();
  });

  it('切换时间桶以 bucket_min=15 重新取数', async () => {
    const user = await openDetail();

    await user.click(screen.getByRole('button', { name: '15 分钟' }));
    await waitFor(() => {
      const last = mockDetail.mock.calls[mockDetail.mock.calls.length - 1][0];
      expect(last.bucketMin).toBe(15);
    });
  });

  it('p_decision 缺失：只展示货币成本并标「IS 分解不可用」，不出现 NaN', async () => {
    mockDetail.mockResolvedValue(buildDetail({
      cost: {
        denominator: null, delay_bps: null, trading_bps: null, opportunity_bps: null,
        delay_cost: -303, trading_cost: -727, opportunity_cost: -485,
        wagner_is_bps: -12.5, residual_bps: null, residual_flag: null,
        arrival_cost_bps: -4.2, opportunity_dominant: false,
        opportunity_highlight: false, note: 'IS 分解不可用（无 BDIB/决策价）',
      },
    }));
    await openDetail();

    expect(screen.getByText('IS 分解不可用（无 BDIB/决策价）')).toBeInTheDocument();
    expect(screen.getByText('延迟成本')).toBeInTheDocument();
    expect(screen.queryAllByText(/NaN|Infinity/)).toHaveLength(0);
  });

  it('单笔成交：跨度显示 N/A（单笔成交），加速度标注 N/A', async () => {
    mockDetail.mockResolvedValue(buildDetail({
      order: { ...buildDetail().order, fill_span_sec: null, speed_shares_per_min: null },
      timeline: {
        ...buildDetail().timeline,
        buckets: [{
          start: '09:35', end: '09:40', fill: 7000, fill_count: 1, vwap: 101.2,
          market_volume: 20000, participation: 0.35, participation_status: 'ok',
          cum_completion: 0.5833, speed_shares_per_min: 1400, accel: null,
        }],
      },
    }));
    await openDetail();

    expect(screen.getByText('N/A（单笔成交）')).toBeInTheDocument();
    expect(screen.getByText(/仅 1 个桶，无加速度可算/)).toBeInTheDocument();
  });

  it('基准价 0（无限价哨兵值）不画基准线也不进图例', async () => {
    mockDetail.mockResolvedValue(buildDetail({
      timeline: {
        ...buildDetail().timeline,
        benchmarks: {
          p_decision: 101.0, p_arrival: 100.9, p_avg: null,
          p_close: 101.5, limit_price: 0,
        },
      },
    }));
    await openDetail();

    // 限价为 0（无限制）不是有效价格：不应出现在基准价行
    expect(screen.queryByText(/限价/)).not.toBeInTheDocument();
    expect(screen.getByText(/决策价 101.00/)).toBeInTheDocument();
  });

  it('关闭详情后再次点击同一行可重新打开（选中态可切换）', async () => {
    const user = await openDetail();

    await user.click(screen.getByRole('button', { name: '关闭详情' }));
    await waitFor(() => expect(screen.queryByText('订单详情')).not.toBeInTheDocument());

    await user.click(screen.getByText('5292736'));
    await waitFor(() => expect(screen.getByText('订单详情')).toBeInTheDocument());
  });

  it('详情失败显示错误与重试，重试再次取数', async () => {
    mockDetail.mockRejectedValueOnce(new Error('[data_not_ready] 数据尚未生成'));
    const user = await openDetail();

    await waitFor(() => expect(screen.getByText(/详情加载失败/)).toBeInTheDocument());
    expect(screen.getByText(/\[data_not_ready\] 数据尚未生成/)).toBeInTheDocument();

    await user.click(within(screen.getByText(/详情加载失败/).closest('div') as HTMLElement)
      .getByRole('button', { name: '重试' }));
    await waitFor(() => expect(mockDetail.mock.calls.length).toBeGreaterThanOrEqual(2));
  });
});
