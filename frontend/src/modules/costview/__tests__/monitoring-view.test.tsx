import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CoverageHeatmap } from '../components/CoverageHeatmap';
import { MonitoringView } from '../components/MonitoringView';
import { ReportView } from '../components/ReportView';
import type { BdibHealthReport, MetricCoverageReport, TcaReportSummary } from '../types';

// ── mock API 层 ──
vi.mock('../services/api', () => ({
  fetchBdibHealth: vi.fn(),
  fetchMetricCoverage: vi.fn(),
  fetchTcaReportSummary: vi.fn(),
  fetchExportHtml: vi.fn(),
}));

import { fetchBdibHealth, fetchExportHtml, fetchMetricCoverage, fetchTcaReportSummary } from '../services/api';

const mockFetchBdibHealth = vi.mocked(fetchBdibHealth);
const mockFetchMetricCoverage = vi.mocked(fetchMetricCoverage);
const mockFetchReportSummary = vi.mocked(fetchTcaReportSummary);
const mockFetchExportHtml = vi.mocked(fetchExportHtml);

// ── 测试数据 ──

const coverageReport: MetricCoverageReport = {
  start_date: '20260803',
  end_date: '20260804',
  metrics: ['fill_count', 'par_rate', 'pnl_vwap'],
  bdib_dependent_metrics: ['par_rate', 'pnl_vwap'],
  group_by_exchange: false,
  rows: [
    {
      date: '20260803',
      exchange: null,
      total_routes: 10,
      coverage: { fill_count: 100, par_rate: 90, pnl_vwap: 45 },
      null_counts: { fill_count: 0, par_rate: 1, pnl_vwap: 6 },
    },
  ],
};

const healthReport: BdibHealthReport = {
  start_date: '20260803',
  end_date: '20260804',
  retention_days: 180,
  dates: [
    {
      date: '20260803',
      fill_tickers: 2,
      bdib_tickers: 1,
      coverage_pct: 50,
      missing_ticker_count: 1,
      missing_tickers: ['MSFT US Equity'],
      sqlite_rows: 1000,
      parquet_rows: 0,
      status: 'partial',
      retention_days_left: 178,
    },
  ],
  summary: {
    total_dates: 1,
    ok_dates: 0,
    partial_dates: 1,
    missing_dates: 0,
    unrecoverable_dates: 0,
    recoverable_gap_dates: 1,
    total_missing_tickers: 1,
    latest_gap_date: '20260803',
  },
};

const reportSummary: TcaReportSummary = {
  filters: {
    start_date: '20260803', end_date: '20260803',
    broker: null, algo: null, symbol: null, exchange: null,
    metrics: [],
  },
  markets: [
    { exchange: 'US', route_count: 10 },
    { exchange: 'HK', route_count: 5 },
  ],
  kpi: {
    route_count: 1232,
    total_route_shares: 133144041,
    weighted_pnl_vwap: 1.86,
    avg_par_rate: 0.17,
    avg_rpm: 0.28,
  },
  daily_series: [
    { date: '20260803', route_count: 1232, weighted_pnl_vwap: 1.86, avg_par_rate: 0.17 },
  ],
  rankings: {
    by_broker: [{ name: 'BROKERA', route_count: 10, weighted_pnl_vwap: -1.2, avg_par_rate: 0.1 }],
    by_algo: [{ name: 'VWAP', route_count: 8, weighted_pnl_vwap: 0.5, avg_par_rate: 0.2 }],
  },
  pnl_vwap_histogram: [{ lower: -2, upper: 0, count: 5 }],
  pwp_curve: [{ rate: 5, avg_pwp: -12.9 }],
  metric_coverage: null,
};

// ── CoverageHeatmap ──

describe('CoverageHeatmap', () => {
  it('渲染日期行与指标列', () => {
    render(<CoverageHeatmap rows={coverageReport.rows} metrics={coverageReport.metrics} />);
    expect(screen.getByText('20260803')).toBeInTheDocument();
    expect(screen.getByText('fill_count')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    // pnl_vwap 覆盖率 45 → 红色档
    expect(screen.getByText('45')).toBeInTheDocument();
  });

  it('BDIB 依赖指标带 * 标记', () => {
    render(<CoverageHeatmap rows={coverageReport.rows} metrics={coverageReport.metrics} />);
    // par_rate / pnl_vwap 两个表头带 *（底部说明另有 1 个）
    const stars = screen.getAllByText('*');
    expect(stars.length).toBe(3);
  });

  it('空数据展示占位', () => {
    render(<CoverageHeatmap rows={[]} metrics={['fill_count']} />);
    expect(screen.getByText('无覆盖率数据')).toBeInTheDocument();
  });
});

// ── MonitoringView ──

describe('MonitoringView', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    mockFetchBdibHealth.mockResolvedValue(healthReport);
    mockFetchMetricCoverage.mockResolvedValue(coverageReport);
  });

  it('加载后渲染概览卡片与健康表', async () => {
    const user = userEvent.setup();
    render(<MonitoringView />);
    await waitFor(() => expect(screen.getByText('监控交易日')).toBeInTheDocument());
    expect(screen.getByText('缺口日（可回补）')).toBeInTheDocument();
    // 两个 API 均被调用
    expect(mockFetchBdibHealth).toHaveBeenCalledWith({ last: 'month' });
    expect(mockFetchMetricCoverage).toHaveBeenCalled();

    // 点击健康表行下钻缺口明细（日期文本在概览卡片/热力图/健康表三处出现，取健康表行）
    const dateCells = screen.getAllByText('20260803');
    await user.click(dateCells[dateCells.length - 1]);
    await waitFor(() => expect(screen.getByText('MSFT US Equity')).toBeInTheDocument());
  });

  it('指标开关清空后热力图显示空态', async () => {
    const user = userEvent.setup();
    render(<MonitoringView />);
    await waitFor(() => expect(screen.getByText('指标覆盖率热力图')).toBeInTheDocument());

    await user.click(screen.getByText('清空'));
    await waitFor(() => expect(screen.getByText('无覆盖率数据')).toBeInTheDocument());
  });

  it('取消勾选指标后热力图列减少', async () => {
    const user = userEvent.setup();
    render(<MonitoringView />);
    await waitFor(() => expect(screen.getByText('指标覆盖率热力图')).toBeInTheDocument());

    // fill_count 文本存在于开关 label + 热力图表头两处；取消勾选后仅剩开关 label
    expect(screen.getAllByText('fill_count').length).toBe(2);
    const checkbox = screen.getAllByRole('checkbox')[0];
    await user.click(checkbox);
    await waitFor(() => {
      expect(screen.getAllByText('fill_count').length).toBe(1);
    });
  });
});

// ── ReportView ──

describe('ReportView', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchReportSummary.mockResolvedValue(reportSummary);
  });

  it('加载后渲染 KPI 卡片', async () => {
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('Route 总数')).toBeInTheDocument());
    expect(screen.getByText('1,232')).toBeInTheDocument();
    expect(screen.getByText('133.14M')).toBeInTheDocument();
    expect(mockFetchReportSummary).toHaveBeenCalledWith(
      expect.objectContaining({ last: 'day' }),
    );
  });

  it('API 失败显示错误提示', async () => {
    mockFetchReportSummary.mockRejectedValue(new Error('boom'));
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('报告加载失败')).toBeInTheDocument());
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('点击导出 HTML 触发 fetchExportHtml 并带阈值参数', async () => {
    mockFetchExportHtml.mockResolvedValue('tca_report_20260803_20260803.html');
    const user = userEvent.setup();
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('Route 总数')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '导出 HTML 报告' }));
    await waitFor(() => expect(mockFetchExportHtml).toHaveBeenCalled());

    const call = mockFetchExportHtml.mock.calls[0][0]!;
    expect(call.last).toBe('day');
    // 默认阈值随请求下发（与 DEFAULT_RULES 对齐）
    expect(call.thresholds).toBeDefined();
    expect(call.thresholds!.tracking_error_bps).toMatchObject({
      mode: 'absolute-above', warning: 10, critical: 25, enabled: true,
    });
  });

  it('导出失败显示错误提示', async () => {
    mockFetchReportSummary.mockResolvedValue(reportSummary);
    mockFetchExportHtml.mockRejectedValue(new Error('export failed'));
    const user = userEvent.setup();
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('Route 总数')).toBeInTheDocument());

    await user.click(screen.getByRole('button', { name: '导出 HTML 报告' }));
    await waitFor(() => expect(screen.getByText('export failed')).toBeInTheDocument());
  });

  it('渲染分市场标签页，切换市场时携带 exchange 重新加载', async () => {
    mockFetchReportSummary.mockResolvedValue(reportSummary);
    const user = userEvent.setup();
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('Route 总数')).toBeInTheDocument());

    // 标签页包含 全部 / US / HK
    expect(screen.getByRole('tab', { name: '全部' })).toBeInTheDocument();
    const usTab = screen.getByRole('tab', { name: 'US' });
    expect(usTab).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'HK' })).toBeInTheDocument();

    // 初始加载两个请求：报告（全部）+ 市场清单
    mockFetchReportSummary.mockClear();
    await user.click(usTab);
    await waitFor(() => {
      expect(mockFetchReportSummary).toHaveBeenCalledWith(
        expect.objectContaining({ last: 'day', exchange: 'US' }),
      );
    });
  });

  it('导出 HTML 时携带当前选中市场', async () => {
    mockFetchReportSummary.mockResolvedValue(reportSummary);
    mockFetchExportHtml.mockResolvedValue('tca_report_20260803_20260803.html');
    const user = userEvent.setup();
    render(<ReportView />);
    await waitFor(() => expect(screen.getByText('Route 总数')).toBeInTheDocument());

    await user.click(screen.getByRole('tab', { name: 'HK' }));
    await waitFor(() => {
      expect(mockFetchReportSummary).toHaveBeenCalledWith(
        expect.objectContaining({ last: 'day', exchange: 'HK' }),
      );
    });

    await user.click(screen.getByRole('button', { name: '导出 HTML 报告' }));
    await waitFor(() => expect(mockFetchExportHtml).toHaveBeenCalled());
    const call = mockFetchExportHtml.mock.calls[0][0]!;
    expect(call.exchange).toBe('HK');
  });
});
