import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnomalyTable } from '../components/report/AnomalyTable';
import type { TcaAnomaly, TcaAnomalyRow } from '../types';

// ── 测试数据 ──

const baseRow: TcaAnomalyRow = {
  date: '20260803',
  order_id: 'O1',
  route_id: 'R1',
  ticker: 'AAPL US Equity',
  exchange: 'US',
  side: 'BUY',
  notional_local: 135000,
  currency: 'USD',
  notional_usd: 135000,
  broker: 'BROKERA',
  algo: 'VWAP',
  completion_rate: 0.9,
  par_rate: 0.15,
  order_par_rate: 0.5,
  fill_count: 20,
  route_shares: 1000,
  fill: 900,
  pnl_vwap: -30,
  arrival_cost_bps: null,
  wagner_is_bps: null,
  opportunity_cost: null,
  unfilled: 100,
  cost_cvar: null,
  order_duration_sec: null,
  recovery_truncated: null,
  hits: [
    { key: 'pnl_vwap_bps', label: 'Pnl VWAP', value: 30, unit: 'bps', severity: 'critical' },
  ],
  severity: 'critical',
  overfill: false,
  order_par_routes: 1,
  order_par_max: 0.5,
  par_suspect: false,
};

const anomaly: TcaAnomaly = {
  count: 2,
  rows: [
    // 数据矛盾行：overfill + 参与率疑似失真（HTML 报告同款标记）
    { ...baseRow, order_id: 'OF1', overfill: true, par_suspect: true },
    // 正常命中行
    { ...baseRow, order_id: 'OK1', overfill: false, par_suspect: false },
  ],
};

// ── P2：双端对齐（HTML 端已披露的「超成交 / >100%」标记在 web 端渲染）──

describe('AnomalyTable 数据质量标记', () => {
  it('命中行渲染「超成交」与「>100%」标记（与 HTML 报告逐字对齐）', () => {
    render(<AnomalyTable anomaly={anomaly} />);

    expect(screen.getByText('超成交')).toBeInTheDocument();
    expect(screen.getByText('>100%')).toBeInTheDocument();
  });

  it('未命中数据矛盾标记的行不渲染标记', () => {
    render(
      <AnomalyTable anomaly={{ ...anomaly, rows: [{ ...baseRow, order_id: 'OK1' }] }} />,
    );

    expect(screen.queryByText('超成交')).not.toBeInTheDocument();
    expect(screen.queryByText('>100%')).not.toBeInTheDocument();
  });

  it('多路由行显示组内最大路由参与率与路由数，不显示不可加总的求和值', () => {
    render(
      <AnomalyTable
        anomaly={{
          ...anomaly,
          rows: [{
            ...baseRow,
            order_id: 'MR1',
            order_par_rate: 3.2,
            order_par_routes: 3,
            order_par_max: 1.5,
            par_suspect: true,
          }],
        }}
      />,
    );

    expect(screen.getByText('max 150.00%')).toBeInTheDocument();
    expect(screen.getByText('3 routes')).toBeInTheDocument();
    expect(screen.queryByText('320.00%')).not.toBeInTheDocument();
  });
});

// ── 筛选标签：市场 / 命中规则 ──

const mixedAnomaly: TcaAnomaly = {
  count: 2,
  rows: [
    {
      ...baseRow,
      order_id: 'US1',
      exchange: 'US',
      hits: [{ key: 'pnl_vwap_bps', label: 'Pnl VWAP', value: 30, unit: 'bps', severity: 'critical' }],
    },
    {
      ...baseRow,
      order_id: 'HK1',
      exchange: 'HK',
      hits: [{ key: 'par_rate', label: '参与率', value: 1.5, unit: 'percent', severity: 'warning' }],
    },
  ],
};

describe('AnomalyTable 筛选标签', () => {
  it('按市场筛选只保留该市场明细', async () => {
    const user = userEvent.setup();
    render(<AnomalyTable anomaly={mixedAnomaly} />);

    await user.click(screen.getByRole('button', { name: '筛选异常市场' }));
    await user.click(screen.getByRole('option', { name: /HK/ }));

    expect(screen.getByText('HK1')).toBeInTheDocument();
    expect(screen.queryByText('US1')).not.toBeInTheDocument();
    expect(screen.getByText(/显示 1 \/ 2 条/)).toBeInTheDocument();
  });

  it('按命中规则筛选只保留命中该规则的明细', async () => {
    const user = userEvent.setup();
    render(<AnomalyTable anomaly={mixedAnomaly} />);

    await user.click(screen.getByRole('button', { name: '筛选异常命中规则' }));
    await user.click(screen.getByRole('option', { name: /参与率/ }));

    expect(screen.getByText('HK1')).toBeInTheDocument();
    expect(screen.queryByText('US1')).not.toBeInTheDocument();
  });

  it('组合筛选无匹配时给出空态，清除后恢复全部', async () => {
    const user = userEvent.setup();
    render(<AnomalyTable anomaly={mixedAnomaly} />);

    await user.click(screen.getByRole('button', { name: '筛选异常市场' }));
    await user.click(screen.getByRole('option', { name: /US/ }));
    await user.click(screen.getByRole('button', { name: '筛选异常命中规则' }));
    await user.click(screen.getByRole('option', { name: /参与率/ }));

    expect(screen.getByText('当前筛选无匹配明细')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '清除筛选' }));

    expect(screen.getByText('US1')).toBeInTheDocument();
    expect(screen.getByText('HK1')).toBeInTheDocument();
  });
});
