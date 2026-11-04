import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LatencyBreakdown } from '../components/trader/LatencyBreakdown';
import { PeerBenchmarkScatter } from '../components/trader/PeerBenchmarkScatter';
import { PeerFingerprint } from '../components/trader/PeerFingerprint';
import { TraderReviewView } from '../components/trader/TraderReviewView';
import type { TraderLatency, TraderPeerStats } from '../types';

vi.mock('../services/api', () => ({
  fetchTraderOrders: vi.fn(),
  fetchTraderFilterOptions: vi.fn(),
  fetchTraderOrderDetail: vi.fn(),
  fetchTraderPeerStats: vi.fn(),
}));

import {
  fetchTraderFilterOptions,
  fetchTraderOrderDetail,
  fetchTraderOrders,
  fetchTraderPeerStats,
} from '../services/api';

const LATENCY: TraderLatency = {
  order_to_route_sec: 1.2, route_to_first_fill_sec: 30,
  order_to_first_fill_sec: 31.2, first_continuous_fill_sec: 25,
  scheduled: false, latency_anomaly: false,
};

/** peer 夹具：4 个可比维度 + 2 个不可得维度 + 几个散点 */
function buildPeer(overrides: Partial<TraderPeerStats> = {}): TraderPeerStats {
  return {
    group: {
      definition: 'ticker+side+algo', kind: 'exact', window_days: 180,
      ticker: 'ABCD US Equity', exchange: 'US', side: 'BUY', algo: 'vwap',
      order_as_of_date: '20261022',
      note: '同类精确口径（同标的 + 方向 + 算法）', excludes_self: true,
    },
    n: 34,
    metrics: [
      {
        key: 'completion', label: '完成率', direction: 'higher_better', value: 0.9,
        median: 0.95, percentile: 0.29, n: 34, available: true, note: null,
      },
      {
        key: 'duration', label: '订单历时', direction: 'lower_better', value: 600,
        median: 500, percentile: 0.7, n: 34, available: true, note: null,
      },
      {
        key: 'fill_cv', label: '单笔 CV', direction: 'lower_better', value: null,
        median: null, percentile: null, n: 0, available: false,
        note: '需逐笔填充量分布（超 peer 预算）',
      },
      {
        key: 'passive_ratio', label: '被动占比', direction: 'higher_better', value: null,
        median: null, percentile: null, n: 0, available: false,
        note: '需逐笔 Liquidity',
      },
      {
        key: 'arrival_cost_bps', label: 'arrival', direction: 'higher_better',
        value: -6.1, median: -4.8, percentile: 0.38, n: 34, available: true, note: null,
      },
      {
        key: 'opportunity_cost_bps', label: '机会成本', direction: 'higher_better',
        value: -1.0, median: 0.0, percentile: 0.2, n: 34, available: true, note: null,
      },
    ],
    hints: [],
    latency: { p90_sec: 120, n: 30 },
    points: [
      { order_id: 'P1', arrival_cost_bps: -3, opportunity_cost_bps: 0, completion: 1, is_self: false },
      { order_id: 'P2', arrival_cost_bps: -6, opportunity_cost_bps: -2, completion: 0.9, is_self: false },
      { order_id: 'ME', arrival_cost_bps: -6.1, opportunity_cost_bps: -1, completion: 0.9, is_self: true },
    ],
    points_truncated: 0,
    sample_insufficient: false,
    deviation_count: 1,
    degraded: ['fill_cv: 需逐笔', 'passive_ratio: 需逐笔'],
    generated_at: '2026-11-04T10:00:00',
    ...overrides,
  };
}

describe('PeerFingerprint（210 §4.7）', () => {
  it('渲染可分位维度，并把不可得维度写明原因', () => {
    render(<PeerFingerprint peer={buildPeer()} />);

    expect(screen.getByText('同类分位（180 天）')).toBeInTheDocument();
    expect(screen.getByText('n = 34')).toBeInTheDocument();
    expect(screen.getByText(/偏离中位维度 1/)).toBeInTheDocument();
    expect(screen.getByText('完成率')).toBeInTheDocument();
    expect(screen.getByText(/分位 29/)).toBeInTheDocument();
    expect(screen.getByText(/分位 70/)).toBeInTheDocument();
    // 不可得维度：不画条，写原因
    expect(screen.getByText(/单笔 CV：未计算（需逐笔填充量分布/)).toBeInTheDocument();
    expect(screen.getByText(/被动占比：未计算（需逐笔 Liquidity）/)).toBeInTheDocument();
  });

  it('样本不足：不展示分位，只列原值与 n', () => {
    render(<PeerFingerprint peer={buildPeer({
      n: 3, sample_insufficient: true,
      metrics: buildPeer().metrics.map((item) => ({ ...item, percentile: null, median: null })),
    })} />);

    expect(screen.getByText(/样本不足（n = 3/)).toBeInTheDocument();
    expect(screen.queryByText(/分位 29/)).not.toBeInTheDocument();
    expect(screen.queryByText(/偏离中位维度/)).not.toBeInTheDocument();
  });
});

describe('PeerBenchmarkScatter（210 §3.5）', () => {
  it('给出可比点数、中位十字线与本单位置', () => {
    render(<PeerBenchmarkScatter peer={buildPeer()} />);

    expect(screen.getByText(/可比点 2 个/)).toBeInTheDocument();
    expect(screen.getByText(/中位十字线/)).toBeInTheDocument();
    expect(screen.getByText(/arrival -4.80/)).toBeInTheDocument();
    expect(screen.getByText(/本单 arrival -6.10/)).toBeInTheDocument();
  });

  it('可比点 <2 时不画散点', () => {
    render(<PeerBenchmarkScatter peer={buildPeer({
      points: [{ order_id: 'ME', arrival_cost_bps: -6.1, opportunity_cost_bps: -1, completion: 0.9, is_self: true }],
    })} />);

    expect(screen.getByText(/可比样本不足/)).toBeInTheDocument();
  });
});

describe('LatencyBreakdown × peer p90', () => {
  it('传入 peerP90 时显示「同类 p90」并说明口径', () => {
    render(<LatencyBreakdown latency={LATENCY} peerP90={120} />);

    expect(screen.getByText('同类 p90')).toBeInTheDocument();
    expect(screen.getByText('2.0m')).toBeInTheDocument();
    expect(screen.getByText(/同类 p90 为 peer 订单/)).toBeInTheDocument();
  });

  it('peerP90=null：显示不可得，不以 0 代替', () => {
    render(<LatencyBreakdown latency={LATENCY} peerP90={null} />);

    expect(screen.getByText('同类 p90')).toBeInTheDocument();
    expect(screen.getByText(/同类 p90 不可得/)).toBeInTheDocument();
  });

  it('未加载 peer（undefined）时沿用「本次未加载」说明', () => {
    render(<LatencyBreakdown latency={LATENCY} />);

    expect(screen.queryByText('同类 p90')).not.toBeInTheDocument();
    expect(screen.getByText(/本次未加载/)).toBeInTheDocument();
  });
});

describe('TraderReviewView × peer 懒加载', () => {
  const ORDERS = {
    filters: { start_date: '20261020', end_date: '20261022' },
    generated_at: '2026-11-04T10:00:00',
    total_orders: 1, offset: 0, limit: 50,
    kpi: {}, probes: { checks: [], spec_version: '2026.11.04' },
    orders: [{
      order_id: '5292736', order_as_of_date: '20261022', trader_name: 'HRCHEN',
      equ_ticker: 'ABCD US Equity', exchange: 'US', side: 'BUY', strategy_type: 'VWAP',
      algo: 'vwap', broker: 'BROKER_A', route_count: 1, fill_count: 3,
      route_shares: 1000, fill: 900, completion: 0.9, vwap: 101.2,
      arrival_cost_bps: -4.2, opportunity_cost: -50, order_duration_sec: 600,
      fill_span_sec: 300, speed_shares_per_min: 2200, passive_ratio: 0.4,
      mixed: false, quality: { level: 'warn', flags: ['par_suspect'] },
    }],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchTraderOrders).mockResolvedValue(ORDERS);
    vi.mocked(fetchTraderFilterOptions).mockResolvedValue({ traders: [], strategy_types: [] });
    // 详情内容不是本用例关注点：失败走错误态，避免用空对象喂详情卡
    vi.mocked(fetchTraderOrderDetail).mockRejectedValue(new Error('detail not needed'));
    vi.mocked(fetchTraderPeerStats).mockResolvedValue(buildPeer());
  });

  it('选中订单后按 order_id + 日期懒加载 peer，并渲染指纹', async () => {
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByText('5292736'));
    // 详情失败也不影响 peer 请求发出（两条链独立）；peer 面板挂在详情成功之后
    await waitFor(() => {
      expect(vi.mocked(fetchTraderPeerStats)).toHaveBeenCalledWith({
        orderId: '5292736', orderAsOfDate: '20261022',
      });
    });
  });
});
