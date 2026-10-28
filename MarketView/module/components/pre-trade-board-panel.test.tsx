import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { PreTradeBoardPanel } from './pre-trade-board-panel';
import type {
  LiveQuotes,
  MarketStateTickerState,
  PreTradeBoardItem,
  PreTradeBoardPayload,
} from '../types';

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
  market_status: 'open',
  market_time: '10:30',
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
      market_status: 'closed',
      market_time: '18:00',
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

const state: MarketStateTickerState = {
  equ_ticker: 'SEC_A US Equity',
  as_of: '2026-10-27T01:00:00+00:00',
  bid: 100,
  ask: 100.02,
  last: 100.01,
  high: 101,
  low: 99,
  volume: 123_456,
  spread_bps: 2,
  spread_vs_baseline_bps: 0.5,
  pct_change_1d: 1.2,
  cumulative_volume_ratio: 1.25,
  flags: [],
  schema_version: 'market-state-v2',
};

const liveOff: LiveQuotes = { byTicker: new Map(), status: 'idle', enabled: false, asOf: null };
const liveOn: LiveQuotes = {
  byTicker: new Map([['SEC_A US Equity', state]]),
  status: 'live',
  enabled: true,
  asOf: '2026-10-27T01:00:00+00:00',
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

const renderPanel = (live: LiveQuotes = liveOff, onUniverseChange = vi.fn()) =>
  render(<PreTradeBoardPanel live={live} onUniverseChange={onUniverseChange} />);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PreTradeBoardPanel', () => {
  it('renders assembled rows with cost and gap badges', async () => {
    stubFetch(payload);

    renderPanel();

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

    renderPanel();

    expect(await screen.findByText('intent intraday · 100%')).toBeInTheDocument();
    expect(screen.getByText('snapshot intraday')).toBeInTheDocument();
    expect(screen.getByText('order_intent · 5m')).toBeInTheDocument();
    expect(screen.getByText('live off')).toBeInTheDocument();
    expect(screen.getByText(/EMSXVIEW_INTRADAY_STATE_ENABLED=true/)).toBeInTheDocument();
  });

  it('renders market status badges per row', async () => {
    stubFetch(payload);

    renderPanel();

    // 交易中 / 已收市两种状态徽标
    expect(await screen.findByText('Trading')).toBeInTheDocument();
    expect(screen.getByText('Closed')).toBeInTheDocument();
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

    renderPanel();

    expect(await screen.findByText('1 unmatched intent(s)')).toBeInTheDocument();
    expect(screen.getByText('unknown_prefix')).toBeInTheDocument();
  });

  it('renders live columns from the shared stream', async () => {
    stubFetch(payload);

    renderPanel(liveOn);

    expect(await screen.findByText('1 live')).toBeInTheDocument();
    expect(screen.queryByText(/EMSXVIEW_INTRADAY_STATE_ENABLED=true/)).not.toBeInTheDocument();
    expect(screen.getByText('100.01')).toBeInTheDocument();
    expect(screen.getByText('2.0')).toBeInTheDocument();
    expect(screen.getByText('1.25x')).toBeInTheDocument();
    // 未覆盖的票保持 n/a
    expect(screen.getAllByText('n/a').length).toBeGreaterThan(0);
  });

  it('reports its universe so the module can subscribe those tickers', async () => {
    stubFetch(payload);
    const onUniverseChange = vi.fn();

    renderPanel(liveOff, onUniverseChange);

    await waitFor(() => {
      expect(onUniverseChange).toHaveBeenCalledWith(['SEC_A US Equity', 'SEC_B US Equity']);
    });
  });

  it('shows guidance when board is empty', async () => {
    stubFetch({ ...payload, items: [] });

    renderPanel();

    expect(await screen.findByText(/No pre-trade board available/)).toBeInTheDocument();
  });

  it('surfaces fetch failures', async () => {
    stubFetch({ detail: 'inbox missing' }, false);

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(/inbox missing/)).toBeInTheDocument();
    });
  });
});
