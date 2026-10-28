import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { MonitorBoardPanel } from './monitor-board-panel';
import type { LiveQuotes, MonitorBoardPayload } from '../types';

const payload: MonitorBoardPayload = {
  pool: {
    pool_id: 'dev-validation',
    label: 'Dev Validation · 8 tickers',
    description: '开发验证池',
    source: 'config',
    as_of: '2026-10-28',
    member_count: 2,
  },
  trade_date: '20261027',
  row_count: 2,
  rows: [
    {
      equ_ticker: 'SEC_A US Equity',
      name: 'Alpha Corp',
      market_status: 'closed',
      market_time: '18:00',
      last: 190.5,
      chg_pct: 1.33,
      close: 188.0,
      prev_close: 188.0,
      total_volume: 3_000_000,
      adv_20d: 2_000_000,
      vol_vs_adv20: 150,
      daily_volatility: 28.9,
      intraday_volatility: 0.23,
      liquidity: 'normal',
      volatility: 'warning',
      risk_notes: ['基线滞后至 20261026', '波动偏高（日 28.9% / 日内 0.23%）'],
      data_gaps: [],
      trade_date: '20261027',
      baseline_date: '20261026',
      bar_count: 2340,
      first_bar_time: '09:30:00',
      last_bar_time: '15:59:50',
      source: 'bars',
    },
    {
      equ_ticker: 'SEC_B EU Equity',
      name: null,
      market_status: 'unknown',
      market_time: null,
      last: null,
      chg_pct: null,
      close: null,
      prev_close: null,
      total_volume: null,
      adv_20d: null,
      vol_vs_adv20: null,
      daily_volatility: null,
      intraday_volatility: null,
      liquidity: 'none',
      volatility: 'none',
      risk_notes: ['无日度基线', '无当日行情'],
      data_gaps: ['baseline', 'bars'],
      trade_date: '20261027',
      baseline_date: null,
      bar_count: 0,
      first_bar_time: null,
      last_bar_time: null,
      source: 'none',
    },
  ],
  highlights: {
    liquidity: [],
    volatility: [
      {
        equ_ticker: 'SEC_A US Equity',
        name: 'Alpha Corp',
        metric: 'Daily / Intraday Vol',
        value: 28.9,
        threshold: '日波动 25/40 或 日内波动 2/3',
        severity: 'warning',
        note: '日 28.9% / 日内 0.23%',
      },
    ],
    risk_notes: [
      {
        equ_ticker: 'SEC_B EU Equity',
        name: null,
        metric: 'Risk notes',
        value: null,
        threshold: '',
        severity: 'critical',
        note: '无日度基线；无当日行情',
      },
    ],
  },
  subscribe_tickers: ['SEC_A US Equity', 'SEC_B EU Equity'],
  generated_at: '2026-10-28T08:00:00+00:00',
};

const liveOff: LiveQuotes = { byTicker: new Map(), status: 'idle', enabled: false, asOf: null };

const names = new Map<string, string>([['SEC_A US Equity', '阿尔法股份有限公司']]);

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

const stubFetch = (body: unknown, ok = true): void => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: unknown) => {
      const url = String(input);
      if (url.includes('monitor-board')) {
        return jsonResponse(body, ok ? 200 : 500);
      }
      return jsonResponse({ detail: 'unknown endpoint' }, 404);
    }),
  );
};

const renderPanel = (overrides: Partial<Parameters<typeof MonitorBoardPanel>[0]> = {}) => {
  const onSelectTicker = vi.fn();
  const onUniverseChange = vi.fn();
  render(
    <MonitorBoardPanel
      live={liveOff}
      names={names}
      selectedTicker={null}
      onSelectTicker={onSelectTicker}
      onUniverseChange={onUniverseChange}
      {...overrides}
    />,
  );
  return { onSelectTicker, onUniverseChange };
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MonitorBoardPanel', () => {
  it('renders the 14 monitor columns', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    // ticker 同时出现在高亮模块与表格，这里只校验表格
    expect(within(table).getByText('SEC_A US Equity')).toBeInTheDocument();
    for (const header of [
      'Ticker',
      'Name',
      'Status',
      'Last',
      'Chg %',
      'Close',
      'Total Vol',
      'ADV 20D',
      'Vol / ADV20',
      'Daily Vol',
      'Intraday Vol',
      'Liquidity',
      'Volatility',
      'Risk notes',
    ]) {
      expect(within(table).getByRole('columnheader', { name: header })).toBeInTheDocument();
    }
    // 中文简称优先于后端 name
    expect(within(table).getByText('阿尔法股份有限公司')).toBeInTheDocument();
  });

  it('keeps highlight panel and table on the same severity', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    expect((await screen.findAllByText('1 alert(s)')).length).toBeGreaterThan(0);
    // 面板里的 warning 徽标与表内 Volatility 列同值
    expect(screen.getAllByText('Warning').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('日 28.9% / 日内 0.23%')).toBeInTheDocument();
  });

  it('shows missing data as dashes and lists risk notes', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    expect(within(table).getByText('无日度基线；无当日行情')).toBeInTheDocument();
    // 缺数据不渲染成 0
    const rowB = within(table).getByText('SEC_B EU Equity').closest('tr');
    expect(rowB).not.toBeNull();
    expect(rowB?.textContent).toContain('—');
  });

  it('opens the detail drawer target when a row is clicked', async () => {
    stubFetch({ success: true, data: payload });
    const { onSelectTicker } = renderPanel();

    const table = await screen.findByRole('table');
    fireEvent.click(within(table).getByText('SEC_A US Equity'));
    expect(onSelectTicker).toHaveBeenCalledWith('SEC_A US Equity');
  });

  it('reports the pool universe for live subscription', async () => {
    stubFetch({ success: true, data: payload });
    const { onUniverseChange } = renderPanel();

    await waitFor(() => {
      expect(onUniverseChange).toHaveBeenCalledWith(['SEC_A US Equity', 'SEC_B EU Equity']);
    });
  });

  it('surfaces fetch failures', async () => {
    stubFetch({ detail: 'monitor board unavailable' }, false);
    renderPanel();

    await waitFor(() => {
      expect(screen.getByText(/monitor board unavailable/)).toBeInTheDocument();
    });
  });
});
