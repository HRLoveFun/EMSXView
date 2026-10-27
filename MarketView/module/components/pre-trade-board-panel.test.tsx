import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { PreTradeBoardPanel } from './pre-trade-board-panel';
import type { MarketStateSnapshot, PreTradeBoardItem, PreTradeBoardPayload } from '../types';

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
    makeItem({
      equ_ticker: 'SEC_B US Equity',
      order_key: '^7000002^0',
      expected_cost_bps: null,
      data_gaps: ['baseline'],
    }),
  ],
  intent_source: 'intraday',
  intent_coverage_pct: 100,
  unmatched: [],
  freshness: [{ dataset: 'order_intent', as_of: '2026-10-27T01:00:00+00:00', lag_minutes: 5 }],
  snapshot_source: 'intraday',
  generated_at: '2026-10-27T01:05:00+00:00',
};

const LIVE_OFF: MarketStateSnapshot = {
  as_of: '',
  enabled: false,
  tickers: [],
  thresholds: {},
  schema_version: 'market-state-v1',
};

const LIVE_ON: MarketStateSnapshot = {
  as_of: '2026-10-27T01:00:00+00:00',
  enabled: true,
  tickers: [
    {
      equ_ticker: 'SEC_A US Equity',
      as_of: '2026-10-27T01:00:00+00:00',
      bid: 100,
      ask: 100.02,
      last: 100.01,
      high: 101,
      low: 99,
      volume: 123456,
      spread_bps: 2,
      spread_vs_baseline_bps: 0.5,
      cumulative_volume_ratio: 1.25,
      flags: [],
      schema_version: 'market-state-v1',
    },
  ],
  thresholds: {},
  schema_version: 'market-state-v1',
};

const stubFetch = (body: unknown, ok = true, live: MarketStateSnapshot = LIVE_OFF): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const isLive = String(input).includes('/api/market-state/snapshot');
      const data = isLive ? live : body;
      const success = isLive ? true : ok;
      return new Response(
        JSON.stringify(success ? { success: true, data, message: '' } : body),
        {
          status: success ? 200 : 500,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    }),
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

  it('exposes intent source, coverage and dataset freshness', async () => {
    stubFetch(payload);

    render(<PreTradeBoardPanel />);

    expect(await screen.findByText('intent intraday · 100%')).toBeInTheDocument();
    expect(screen.getByText('snapshot intraday')).toBeInTheDocument();
    expect(screen.getByText('order_intent · 5m')).toBeInTheDocument();
    expect(screen.getByText('live off')).toBeInTheDocument();
  });

  it('lists unmatched intents with reasons', async () => {
    stubFetch({
      ...payload,
      intent_coverage_pct: 50,
      unmatched: [
        {
          order_key: '^7000003^0',
          equ_ticker: 'SEC_C US Equity',
          pm_note: '^7000003^0',
          reason: 'unknown_prefix',
        },
      ],
    });

    render(<PreTradeBoardPanel />);

    expect(await screen.findByText('1 unmatched intent(s)')).toBeInTheDocument();
    expect(screen.getByText('unknown_prefix')).toBeInTheDocument();
  });

  it('renders live columns from market state snapshot', async () => {
    stubFetch(payload, true, LIVE_ON);

    render(<PreTradeBoardPanel />);

    expect(await screen.findByText('1 live')).toBeInTheDocument();
    expect(screen.getByText('100.01')).toBeInTheDocument();
    expect(screen.getByText('2.0')).toBeInTheDocument();
    expect(screen.getByText('1.25x')).toBeInTheDocument();
    // 未覆盖的票保持 n/a
    expect(screen.getAllByText('n/a').length).toBeGreaterThan(0);
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
