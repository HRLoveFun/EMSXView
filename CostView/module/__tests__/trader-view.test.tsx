import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TraderKpiStrip } from '../components/trader/TraderKpiStrip';
import { TraderReviewView } from '../components/trader/TraderReviewView';
import type { TraderListPayload } from '../types';

// ── mock API 层（视图只依赖 services/api，不触网）──
vi.mock('../services/api', () => ({
  fetchTraderOrders: vi.fn(),
  fetchTraderFilterOptions: vi.fn(),
  // PR-4：视图新增详情取数依赖，模块 mock 必须一并提供（否则点击行会 TypeError）
  fetchTraderOrderDetail: vi.fn(),
  // PR-8：同类分位懒加载依赖；必须返回 Promise（undefined 会让 useAsyncData 读 .then 崩）
  fetchTraderPeerStats: vi.fn(async () => null),
  // PR-10：CSV 导出入口
  exportTraderCsv: vi.fn(async () => 'trader_orders.csv'),
}));

import {
  exportTraderCsv,
  fetchTraderFilterOptions,
  fetchTraderOrders,
} from '../services/api';

const mockOrders = vi.mocked(fetchTraderOrders);
const mockOptions = vi.mocked(fetchTraderFilterOptions);
const mockExport = vi.mocked(exportTraderCsv);

// ── 测试数据 ──

function buildPayload(overrides: Partial<TraderListPayload> = {}): TraderListPayload {
  return {
    filters: { start_date: '20261020', end_date: '20261022' },
    generated_at: '2026-11-04T10:00:00',
    // 共 60 条使「下一页」可用（页大小 50）；orders 仅示例两行
    total_orders: 60,
    offset: 0,
    limit: 50,
    kpi: {
      orders: { value: 2, n: 2, scope: 'full' },
      low_completion_ratio: { value: 0.5, n: 2, denominator: 2 },
      opp_dominant_ratio: { value: null, n: 0, denominator: 0 },
      passive_ratio: { value: 0.25, n: 600, unknown_share: 0.1, scope: 'current_page' },
      release_delay_p90: { value: 120, n: 1, denominator: 2, scope: 'continuous_only' },
      anomaly_orders: { value: 1, critical: 0, warning: 1, n: 2 },
      peer_small_orders: { value: null, n: 2, note: 'peer 样本量随 peer 端点（PR-2）接入' },
    },
    probes: {
      checks: [
        { id: 'quantity', checked: true, triggered: 0, affected_kpis: [], note: null },
        { id: 'participation', checked: true, triggered: 1, affected_kpis: ['par_rate'], note: null },
        { id: 'cost_missing', checked: true, triggered: 0, affected_kpis: [], note: null },
        {
          id: 'fill_quality', checked: false, triggered: null,
          affected_kpis: ['passive_ratio'], note: '当前页无逐笔，未检查（不伪装通过）',
        },
      ],
      spec_version: '2026.11.03',
    },
    orders: [
      {
        order_id: '5292736', order_as_of_date: '20261022', trader_name: 'HRCHEN',
        equ_ticker: 'ABCD US Equity', exchange: 'US', side: 'BUY', strategy_type: 'VWAP',
        algo: 'vwap', broker: 'BROKER_A', route_count: 2, fill_count: 6,
        route_shares: 12000, fill: 11000, completion: 0.9167, vwap: 101.23,
        arrival_cost_bps: -4.2, opportunity_cost: -50, order_duration_sec: 600,
        fill_span_sec: 300, speed_shares_per_min: 2200, passive_ratio: 0.4,
        mixed: true, quality: { level: 'warn', flags: ['par_suspect'] },
      },
      {
        order_id: '5292737', order_as_of_date: '20261022', trader_name: 'WLUO125',
        equ_ticker: 'BBCD US Equity', exchange: 'US', side: 'SELL', strategy_type: 'CLOSE',
        algo: 'close', broker: 'BROKER_B', route_count: 1, fill_count: 1,
        route_shares: 5000, fill: 5000, completion: 1.0, vwap: 55.5,
        arrival_cost_bps: null, opportunity_cost: null, order_duration_sec: null,
        fill_span_sec: null, speed_shares_per_min: null, passive_ratio: null,
        mixed: false, quality: { level: 'info', flags: ['single_fill', 'scheduled_close'] },
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  mockOptions.mockResolvedValue({
    traders: ['HRCHEN', 'WLUO125'],
    strategy_types: ['VWAP', 'CLOSE'],
    symbols: ['ABCD US Equity'],
    brokers: ['BROKER_A'],
    algos: ['vwap'],
  });
  mockOrders.mockResolvedValue(buildPayload());
});

describe('TraderReviewView', () => {
  it('渲染 KPI 条、可信度横幅与订单行（mixed / 质量徽章 / N/A）', async () => {
    render(<TraderReviewView />);

    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());
    // KPI 卡：null 一律「—」，不显示 0
    expect(screen.getByText('订单数')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    // 可信度横幅：未检查显式可见（fill_quality 探针 checked=false + note）
    expect(screen.getByText(/逐笔质量/)).toBeInTheDocument();
    expect(screen.getByText(/未检查/)).toBeInTheDocument();
    // 订单行：mixed 标记 + 质量徽章 + 单笔成交 N/A（跨度/速度多列为 N/A）
    expect(screen.getByText('mixed')).toBeInTheDocument();
    expect(screen.getByTitle('参与率失真')).toBeInTheDocument();
    expect(screen.getAllByText('N/A').length).toBeGreaterThan(0);
  });

  it('翻页：下一页以 offset=50 请求', async () => {
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => {
      const lastCall = mockOrders.mock.calls[mockOrders.mock.calls.length - 1][0];
      expect(lastCall.offset).toBe(50);
    });
  });

  it('筛选变更回到第 1 页并携带筛选参数（质量 = 超成交）', async () => {
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '下一页' }));
    await waitFor(() => {
      expect(mockOrders.mock.calls[mockOrders.mock.calls.length - 1][0].offset).toBe(50);
    });
    // 质量筛选收在「更多筛选」里，展开后一次点击完成切换
    await user.click(screen.getByRole('button', { name: /更多筛选/ }));
    await user.click(screen.getByRole('button', { name: '超成交' }));
    await waitFor(() => {
      const lastCall = mockOrders.mock.calls[mockOrders.mock.calls.length - 1][0];
      expect(lastCall.offset).toBe(0);
      expect(lastCall.quality).toBe('overfill');
    });
  });

  it('保存筛选视图并可一键套用', async () => {
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: /更多筛选/ }));
    await user.click(screen.getByRole('button', { name: '超成交' }));
    expect(screen.getByText('质量：超成交')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /保存当前筛选/ }));
    await user.type(screen.getByPlaceholderText('视图名称，如 每日复盘'), '每日复盘');
    await user.click(screen.getByRole('button', { name: '保存视图' }));
    expect(screen.getByRole('button', { name: '每日复盘' })).toBeInTheDocument();

    // 手动改回全部，再套用视图应恢复保存时的口径
    const qualityGroup = screen.getByRole('group', { name: '质量筛选' });
    await user.click(within(qualityGroup).getByRole('button', { name: '全部' }));
    await waitFor(() => {
      const lastCall = mockOrders.mock.calls[mockOrders.mock.calls.length - 1][0];
      expect(lastCall.quality).toBe('all');
    });

    await user.click(screen.getByRole('button', { name: '每日复盘' }));
    await waitFor(() => {
      const lastCall = mockOrders.mock.calls[mockOrders.mock.calls.length - 1][0];
      expect(lastCall.quality).toBe('overfill');
      expect(lastCall.offset).toBe(0);
    });
  });

  it('空结果（200 + total_orders=0）显示空态而非错误', async () => {
    mockOrders.mockResolvedValue(buildPayload({
      total_orders: 0, offset: 0, orders: [],
    }));
    render(<TraderReviewView />);

    await waitFor(() => expect(screen.getByText(/当前筛选无订单/)).toBeInTheDocument());
  });

  it('导出订单 / 成交 CSV 使用当前筛选（不含分页在 api 层剥离）', async () => {
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Export orders CSV' }));
    await waitFor(() => expect(mockExport).toHaveBeenCalledTimes(1));
    expect(mockExport.mock.calls[0][0]).toBe('orders');
    expect(mockExport.mock.calls[0][1]).toMatchObject({
      quality: 'all', sort: 'date', sortDir: 'desc',
    });

    await user.click(screen.getByRole('button', { name: 'Export fills CSV' }));
    await waitFor(() => expect(mockExport).toHaveBeenCalledTimes(2));
    expect(mockExport.mock.calls[1][0]).toBe('fills');
  });

  it('导出上限 422 显示 Export failed 与后端文案（提示缩小范围）', async () => {
    mockExport.mockRejectedValueOnce(
      new Error('[export_too_large] 导出订单数 60,000 超过上限 50,000'),
    );
    const user = userEvent.setup();
    render(<TraderReviewView />);
    await waitFor(() => expect(screen.getByText('5292736')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: 'Export orders CSV' }));

    await waitFor(() => expect(screen.getByText('Export failed')).toBeInTheDocument());
    expect(screen.getByText(/超过上限 50,000/)).toBeInTheDocument();
    expect(screen.getByText(/narrow the date range/)).toBeInTheDocument();
  });

  it('请求失败显示错误与重试按钮，重试再次发起请求', async () => {
    const user = userEvent.setup();
    mockOrders.mockRejectedValueOnce(new Error('[data_not_ready] 数据尚未生成'));
    render(<TraderReviewView />);

    await waitFor(() => expect(screen.getByText('订单查询失败')).toBeInTheDocument());
    expect(screen.getByText(/\[data_not_ready\] 数据尚未生成/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(mockOrders.mock.calls.length).toBeGreaterThanOrEqual(2));
  });
});

describe('TraderKpiStrip（纯展示契约）', () => {
  it('null 值显示「—」并保留口径注记', () => {
    const payload = buildPayload();
    render(<TraderKpiStrip kpi={payload.kpi} />);

    expect(screen.getByText('被动占比（当前页）')).toBeInTheDocument();
    expect(screen.getByText('25.0%')).toBeInTheDocument();
    expect(screen.getByText('释放延迟 p90')).toBeInTheDocument();
    expect(screen.getByText('120s')).toBeInTheDocument();
    // opp_dominant_ratio / peer_small_orders 为 null → 「—」
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });
});
