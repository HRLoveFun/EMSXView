import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { PoolBoardPanel } from './pool-board-panel';
import type { LiveQuotes, MarketStateTickerState, PoolBoardPayload } from '../types';

const payload: PoolBoardPayload = {
  trade_date: '20260408',
  pool_id: 'all',
  row_count: 2,
  assumptions: {
    notional_usd: 1_000_000,
    annual_vol_pct: 25,
    duration_min: 60,
    model_calibrated: false,
    note: '参考成本：按 100 万美元名义额 ÷ 收盘价得 qty，再按 qty ÷ ADV20 参与率、25% 年化波动、60 分钟执行窗口估算；仅用于池内横向比较，不是订单级预测（K3）',
  },
  rows: [
    {
      equ_ticker: 'SEC_A US Equity',
      daily_close: 100,
      total_volume: 1_000_000,
      adv_20d: 2_000_000,
      volume_vs_adv20_pct: 50,
      daily_volatility: 2.1,
      intraday_volatility: 1.4,
      liquidity_alert: 'none',
      volatility_alert: 'none',
      log_volume_z: 1.2,
      vol_percentile: 78,
      adv5_adv60_ratio: 1.1,
      expected_cost_bps: 12.5,
      timing_risk_bps: 3.2,
      in_domain: true,
      model_version: 'cost-model-v1',
      data_gaps: [],
    },
    {
      equ_ticker: 'SEC_B US Equity',
      daily_close: 50,
      total_volume: 500_000,
      adv_20d: 1_000_000,
      volume_vs_adv20_pct: 50,
      daily_volatility: 3,
      intraday_volatility: 2,
      liquidity_alert: 'warning',
      volatility_alert: 'none',
      log_volume_z: null,
      vol_percentile: null,
      adv5_adv60_ratio: null,
      expected_cost_bps: null,
      timing_risk_bps: null,
      in_domain: false,
      model_version: null,
      data_gaps: ['baseline', 'cost_model'],
    },
  ],
  generated_at: '2026-10-27T01:00:00+00:00',
};

const liveQuote: MarketStateTickerState = {
  equ_ticker: 'SEC_A US Equity',
  as_of: '2026-10-27T10:00:00',
  bid: 99.9,
  ask: 100.1,
  last: 100.55,
  high: 101,
  low: 99,
  volume: 123_456,
  spread_bps: 2,
  spread_vs_baseline_bps: null,
  pct_change_1d: 1.234,
  cumulative_volume_ratio: null,
  flags: [],
  schema_version: 'market-state-v2',
};

const liveOff: LiveQuotes = {
  byTicker: new Map(),
  status: 'idle',
  enabled: false,
  asOf: null,
};

const liveOn = (overrides: Partial<MarketStateTickerState> = {}): LiveQuotes => ({
  byTicker: new Map([['SEC_A US Equity', { ...liveQuote, ...overrides }]]),
  status: 'live',
  enabled: true,
  asOf: '2026-10-27T10:00:00',
});

const stubFetch = (body: unknown, ok = true): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes('pool-board')) {
        return { ok, json: async () => body };
      }
      return { ok: false, json: async () => ({ detail: 'unknown endpoint' }) };
    }),
  );
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PoolBoardPanel', () => {
  it('renders metrics, cost reference and explicit gaps', async () => {
    stubFetch({ success: true, data: payload });

    render(<PoolBoardPanel poolId="all" tradeDate="20260408" live={liveOff} />);

    expect(await screen.findByText('SEC_A US Equity')).toBeInTheDocument();
    expect(screen.getByText('2 rows')).toBeInTheDocument();
    expect(screen.getByText('12.5')).toBeInTheDocument();
    expect(screen.getByText('78.0%')).toBeInTheDocument();
    expect(screen.getByText('模型未校准')).toBeInTheDocument();
    expect(screen.getByText('基线缺失 / 成本模型缺失')).toBeInTheDocument();
  });

  it('shows the cost assumption text', async () => {
    stubFetch({ success: true, data: payload });

    render(<PoolBoardPanel poolId="all" live={liveOff} />);

    expect(await screen.findByText(/ADV20 参与率/)).toBeInTheDocument();
  });

  it('shows empty state when the pool has no rows', async () => {
    stubFetch({ success: true, data: { ...payload, row_count: 0, rows: [] } });

    render(<PoolBoardPanel poolId="liquidity-watch" tradeDate="20260408" live={liveOff} />);

    expect(await screen.findByText(/No rows for pool/)).toBeInTheDocument();
  });

  it('surfaces fetch failures', async () => {
    stubFetch({ detail: 'unknown pool' }, false);

    render(<PoolBoardPanel poolId="nope" live={liveOff} />);

    await waitFor(() => {
      expect(screen.getByText(/unknown pool/)).toBeInTheDocument();
    });
  });

  it('renders live last/change/spread/volume ratio from the market-state stream', async () => {
    stubFetch({ success: true, data: payload });

    render(<PoolBoardPanel poolId="all" tradeDate="20260408" live={liveOn()} />);

    expect(await screen.findByText('1 live')).toBeInTheDocument();
    expect(screen.getByText('100.55')).toBeInTheDocument();
    expect(screen.getByText('+1.23%')).toBeInTheDocument();
    expect(screen.getByText('99.90')).toBeInTheDocument();
    expect(screen.getByText('100.10')).toBeInTheDocument();
    expect(screen.getByText('2.00')).toBeInTheDocument();
    // 实时参与率：123,456 ÷ ADV20 2,000,000 = 6.2%
    expect(screen.getByText('6.2%')).toBeInTheDocument();
    // 未订阅到行情的标的保持 n/a
    expect(screen.getAllByText('n/a').length).toBeGreaterThan(0);
  });

  it('marks the data source when the stream falls back to REST polling', async () => {
    stubFetch({ success: true, data: payload });

    render(<PoolBoardPanel poolId="all" live={{ ...liveOn(), status: 'polling' }} />);

    expect(await screen.findByText('1 live · REST')).toBeInTheDocument();
  });

  it('shows a flag badge with server-side evidence when a live alert fires', async () => {
    stubFetch({ success: true, data: payload });

    render(
      <PoolBoardPanel
        poolId="all"
        live={liveOn({
          flags: [
            {
              code: 'SPREAD_VS_BASELINE_WIDE',
              severity: 'WARN',
              evidence: '12.00 bps > 5.0 bps',
            },
          ],
        })}
      />,
    );

    expect(await screen.findByTitle(/SPREAD_VS_BASELINE_WIDE: 12.00 bps/)).toBeInTheDocument();
  });

  it('reports its universe so the module can subscribe those tickers', async () => {
    stubFetch({ success: true, data: payload });
    const onUniverseChange = vi.fn();

    render(
      <PoolBoardPanel
        poolId="all"
        tradeDate="20260408"
        live={liveOff}
        onUniverseChange={onUniverseChange}
      />,
    );

    await waitFor(() => {
      expect(onUniverseChange).toHaveBeenCalledWith(['SEC_A US Equity', 'SEC_B US Equity']);
    });
  });
});
