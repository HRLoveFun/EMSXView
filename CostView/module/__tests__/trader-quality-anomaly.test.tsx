import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CredibilityBanner } from '../components/trader/CredibilityBanner';
import { AnomalySummary } from '../components/trader/AnomalySummary';
import { TraderReviewView } from '../components/trader/TraderReviewView';
import type { TraderAnomalySummary, TraderProbeCheck } from '../types';

vi.mock('../services/api', () => ({
  fetchTraderOrders: vi.fn(),
  fetchTraderFilterOptions: vi.fn(),
  fetchTraderOrderDetail: vi.fn(),
}));

import {
  fetchTraderFilterOptions,
  fetchTraderOrderDetail,
  fetchTraderOrders,
} from '../services/api';

const PROBES_CLEAN: TraderProbeCheck[] = [
  { id: 'quantity', checked: true, triggered: 0, affected_kpis: [], note: null },
  { id: 'participation', checked: true, triggered: 0, affected_kpis: [], note: null },
  { id: 'cost_missing', checked: true, triggered: 0, affected_kpis: [], note: null },
  { id: 'fill_quality', checked: true, triggered: 0, affected_kpis: [], note: null },
];

const PROBES_MIXED: TraderProbeCheck[] = [
  { id: 'quantity', checked: true, triggered: 2, affected_kpis: ['completion', 'opportunity_cost'], note: null },
  { id: 'participation', checked: true, triggered: 14, affected_kpis: ['par_rate'], note: null },
  { id: 'cost_missing', checked: true, triggered: 0, affected_kpis: [], note: null },
  {
    id: 'fill_quality', checked: false, triggered: null, affected_kpis: ['passive_ratio'],
    note: '范围>31 天，未检查',
  },
];

const SUMMARY: TraderAnomalySummary = {
  orders_total: 3,
  critical: 1,
  warning: 2,
  rule_orders: 2,
  quality_orders: 2,
  by_rule: [
    { key: 'fill_pct', label: '完成率', count: 2, critical: 1 },
    { key: 'pnl_vwap_bps', label: 'pnl_vwap', count: 1, critical: 0 },
  ],
  top_orders: [
    {
      order_id: 'A100', order_as_of_date: '20261022', ticker: 'ABCD US Equity', side: 'BUY',
      severity: 'critical',
      reasons: [{ key: 'fill_pct', label: '完成率', severity: 'critical', value: 42, unit: 'percent' }],
    },
    {
      order_id: 'A101', order_as_of_date: '20261022', ticker: 'BBCD US Equity', side: 'SELL',
      severity: 'warning',
      reasons: [{ key: 'pnl_vwap_bps', label: 'pnl_vwap', severity: 'warning', value: 12, unit: 'bps' }],
    },
  ],
  scope: 'order-level',
  note: '订单级口径（成交股数加权 pnl_vwap / 完成率 / 组内最大路由参与率）',
};

describe('CredibilityBanner（210 §4.12）', () => {
  it('全部通过时仍渲染，并写明「全部通过」', () => {
    render(<CredibilityBanner checks={PROBES_CLEAN} />);

    expect(screen.getByText('数据可信度')).toBeInTheDocument();
    expect(screen.getByText(/4 类检查全部通过/)).toBeInTheDocument();
  });

  it('混合态：汇总「已检查 3/4 类 · 触发 2 类 · 影响 3 个 KPI」', () => {
    render(<CredibilityBanner checks={PROBES_MIXED} />);

    // 受影响 KPI = {完成率, 机会成本, 参与率}（未检查项的 KPI 不计入）
    expect(screen.getByText(/已检查 3\/4 类 · 触发 2 类 · 影响 3 个 KPI/)).toBeInTheDocument();
    // 未检查项显式标注，不并入「通过」
    expect(screen.getByText(/逐笔质量 未检查/)).toBeInTheDocument();
    expect(screen.getByText(/参与率异常 14/)).toBeInTheDocument();
  });

  it('折叠只影响明细：展开后显示受影响 KPI 与未检查原因', async () => {
    const user = userEvent.setup();
    render(<CredibilityBanner checks={PROBES_MIXED} />);

    const toggle = screen.getByRole('button', { name: /展开口径/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/影响 KPI：完成率、机会成本/)).not.toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/影响 KPI：完成率、机会成本/)).toBeInTheDocument();
    expect(screen.getByText(/范围>31 天，未检查/)).toBeInTheDocument();
    expect(screen.getByText(/0 触发不等于数据无缺陷/)).toBeInTheDocument();
  });
});

describe('AnomalySummary（210 §4.11）', () => {
  it('渲染计数分档、按规则计数与口径说明', () => {
    render(<AnomalySummary summary={SUMMARY} />);

    expect(screen.getByText('我的异常订单')).toBeInTheDocument();
    expect(screen.getByText('3 单')).toBeInTheDocument();
    // 表头分档与按规则行的 critical 标注都会出现，取并集断言
    expect(screen.getAllByText(/critical 1/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/warning 2/).length).toBeGreaterThanOrEqual(1);
    // 按规则（含 critical 标注）
    expect(screen.getByText('完成率')).toBeInTheDocument();
    expect(screen.getByText(/（critical 1）/)).toBeInTheDocument();
    // 口径与并集说明
    expect(screen.getByText(/规则命中 2 单、质量标记 2 单/)).toBeInTheDocument();
  });

  it('点击异常订单回调 (order_id, 日期)；未提供导航时「查看全部」禁用', async () => {
    const user = userEvent.setup();
    const onSelectOrder = vi.fn();
    render(<AnomalySummary summary={SUMMARY} onSelectOrder={onSelectOrder} />);

    await user.click(screen.getByRole('button', { name: /A100/ }));
    expect(onSelectOrder).toHaveBeenCalledWith('A100', '20261022');
    expect(screen.getByRole('button', { name: /查看全部/ })).toBeDisabled();
  });

  it('0 单时显示空态而非空白', () => {
    render(<AnomalySummary summary={{ ...SUMMARY, orders_total: 0, by_rule: [], top_orders: [] }} />);

    expect(screen.getByText(/当前筛选范围无异常订单/)).toBeInTheDocument();
  });
});

describe('TraderReviewView × 异常摘要联动', () => {
  const ORDERS = {
    filters: { start_date: '20261020', end_date: '20261022' },
    generated_at: '2026-11-04T10:00:00',
    total_orders: 1, offset: 0, limit: 50,
    kpi: { anomaly_orders: { value: 3, n: 1, critical: 1, warning: 2 } },
    probes: { checks: PROBES_MIXED, spec_version: '2026.11.04' },
    anomaly_summary: SUMMARY,
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

  it('「查看全部」把 Report tab 交给宿主导航；点异常订单直接按订单+日期取详情', async () => {
    vi.mocked(fetchTraderOrders).mockResolvedValue(ORDERS);
    vi.mocked(fetchTraderFilterOptions).mockResolvedValue({ traders: [], strategy_types: [] });
    // 详情内容不是本用例关注点：让请求失败走错误态，避免用空对象喂给详情卡（会崩）
    vi.mocked(fetchTraderOrderDetail).mockRejectedValue(new Error('detail not needed'));
    const user = userEvent.setup();
    const onNavigateTab = vi.fn();
    render(<TraderReviewView onNavigateTab={onNavigateTab} />);

    await waitFor(() => expect(screen.getByText('我的异常订单')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /查看全部/ }));
    expect(onNavigateTab).toHaveBeenCalledWith('report');

    // 摘要里的订单不在当前页也能选中（按 order_id + 日期取详情）
    await user.click(screen.getByRole('button', { name: /A101/ }));
    await waitFor(() => {
      const last = vi.mocked(fetchTraderOrderDetail).mock.calls.at(-1)?.[0];
      expect(last).toMatchObject({ orderId: 'A101', orderAsOfDate: '20261022' });
    });
  });
});
