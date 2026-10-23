import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { PreTradeBoardPanel } from './pre-trade-board-panel';
import type { PreTradeBoardItem, PreTradeBoardPayload } from '../types';

const makeItem = (overrides: Partial<PreTradeBoardItem> = {}): PreTradeBoardItem => ({
  equ_ticker: 'SEC_A US Equity',
  order_key: '^7000001^0',
  benchmark: 'VWAP',
  close_pct: null,
  qty: 50000,
  log_volume_z: 1.23,
  vol_percentile: 80,
  adv5_adv60_ratio: 0.95,
  market_code: 'US',
  liq_regime: 'normal',
  vol_regime: 'normal',
  expected_cost_bps: 12.5,
  timing_risk_bps: 8.0,
  in_domain: true,
  model_version: 'cost-model-v1',
  model_calibrated: false,
  data_gaps: [],
  ...overrides,
});

const payload: PreTradeBoardPayload = {
  trade_date: null,
  export_file_name: '',
  schema_version: 'market-to-execution-v2',
  items: [
    makeItem(),
    makeItem({ equ_ticker: 'SEC_B US Equity', order_key: '^7000002^0', expected_cost_bps: null, data_gaps: ['baseline'] }),
  ],
};

const stubFetch = (body: unknown, ok = true): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () =>
      new Response(JSON.stringify(ok ? { success: true, data: body, message: '' } : body), {
        status: ok ? 200 : 500,
        headers: { 'Content-Type': 'application/json' },
      }),
    ),
  );
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PreTradeBoardPanel', () => {
  it('renders assembled rows with cost and gap badges', async () => {
    stubFetch(payload);

    render(<PreTradeBoardPanel />);

    expect(await screen.findByText('schema market-to-execution-v2')).toBeInTheDocument();
    expect(screen.getByText('2 order(s)')).toBeInTheDocument();
    expect(screen.getByText('1 with cost')).toBeInTheDocument();
    expect(screen.getByText('SEC_A US Equity')).toBeInTheDocument();
    // CostBadge 的 span 含多个文本节点（值 + 未达标星号），用正则匹配
    const costBadge = screen.getAllByText(/12\.5 bps/)[0];
    expect(costBadge).toHaveAttribute('title', expect.stringContaining('not calibrated'));
    // 缺口徽标可见（SEC_B 缺 baseline）
    expect(screen.getByText('gaps: baseline')).toBeInTheDocument();
    // 未达标脚注
    expect(screen.getByText(/not yet calibrated/)).toBeInTheDocument();
  });

  it('shows guidance when board is empty', async () => {
    stubFetch({ ...payload, items: [] });

    render(<PreTradeBoardPanel />);

    expect(await screen.findByText(/No pre-trade board available/)).toBeInTheDocument();
  });

  it('surfaces fetch failures', async () => {
    stubFetch({ detail: 'inbox missing' }, false);

    render(<PreTradeBoardPanel />);

    await waitFor(() => {
      expect(screen.getByText(/inbox missing/)).toBeInTheDocument();
    });
  });
});
