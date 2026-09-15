import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
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
  order_par_gt100: false,
};

const anomaly: TcaAnomaly = {
  count: 2,
  rows: [
    // 数据矛盾行：overfill + 订单参与率 >100%（HTML 报告同款标记）
    { ...baseRow, order_id: 'OF1', overfill: true, order_par_gt100: true },
    // 正常命中行
    { ...baseRow, order_id: 'OK1', overfill: false, order_par_gt100: false },
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
});
