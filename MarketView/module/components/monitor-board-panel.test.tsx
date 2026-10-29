import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { MonitorBoardPanel } from './monitor-board-panel';
import type { LiveQuotes, MonitorBoardPayload } from '../types';

const payload: MonitorBoardPayload = {
  pool: {
    pool_id: 'dev-validation',
    label: 'Dev Validation · 8 tickers',
    description: 'Dev validation pool',
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
      risk_notes: ['Baseline stale to 20261026', 'Volatility elevated (daily 28.9% / intraday 0.23%)'],
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
      risk_notes: ['No daily baseline', 'No intraday bars'],
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
        threshold: 'daily vol 25/40 or intraday vol 2/3',
        severity: 'warning',
        note: 'daily 28.9% / intraday 0.23%',
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
        note: 'No daily baseline; No intraday bars',
      },
      {
        equ_ticker: 'SEC_A US Equity',
        name: 'Alpha Corp',
        metric: 'Risk notes',
        value: null,
        threshold: '',
        severity: 'warning',
        note: 'Baseline stale to 20261026; Volatility elevated (daily 28.9% / intraday 0.23%)',
      },
    ],
  },
  subscribe_tickers: ['SEC_A US Equity', 'SEC_B EU Equity'],
  generated_at: '2026-10-28T08:00:00+00:00',
};

const liveOff: LiveQuotes = { byTicker: new Map(), status: 'idle', enabled: false, asOf: null };

const names = new Map<string, string>([['SEC_A US Equity', 'ALPHA CORP']]);

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

const marketChip = (market: string): HTMLElement =>
  screen.getByRole('button', { name: new RegExp(`^${market} · \\d`) });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MonitorBoardPanel', () => {
  it('renders the 15 monitor columns including Exchange first', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    const headers = within(table)
      .getAllByRole('columnheader')
      .map((header) => header.textContent?.replace(/[▾▼]/g, '').trim());
    expect(headers).toEqual([
      'Exchange',
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
    ]);
    // Name 列走 SHORT_NAME（names map 优先）
    expect(within(table).getByText('ALPHA CORP')).toBeInTheDocument();
    // Exchange 列取 ticker 后缀
    expect(within(table).getAllByText('US').length).toBeGreaterThan(0);
    expect(within(table).getAllByText('EU').length).toBeGreaterThan(0);
  });

  it('shares market chips across all modules and reveals tickers on click', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const notes = await screen.findByRole('group', { name: 'Risk notes' });
    const volatility = screen.getByRole('group', { name: 'Volatility' });
    // 默认不展开任何市场的股票
    expect(within(notes).getByText('Select a market above to list signals')).toBeInTheDocument();
    expect(within(volatility).getByText('Select a market above to list signals')).toBeInTheDocument();

    // 共享市场标签：点一次，三个模块同时生效
    fireEvent.click(marketChip('US'));
    expect(within(notes).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(volatility).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(notes).queryByText('SEC_B EU Equity')).not.toBeInTheDocument();

    // 再次点击反选取消
    fireEvent.click(marketChip('US'));
    expect(within(notes).queryByText('SEC_A US Equity')).not.toBeInTheDocument();
  });

  it('supports multi-select, select-all and invert for market chips', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const notes = await screen.findByRole('group', { name: 'Risk notes' });
    fireEvent.click(marketChip('US'));
    fireEvent.click(marketChip('EU'));
    expect(within(notes).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(notes).getByText('SEC_B EU Equity')).toBeInTheDocument();

    // 一键反选：两个都选 → 全不选
    fireEvent.click(screen.getByRole('button', { name: 'Invert markets' }));
    expect(within(notes).getByText('Select a market above to list signals')).toBeInTheDocument();

    // 一键全选：两个市场的股票都展开
    fireEvent.click(screen.getByRole('button', { name: 'Select all markets' }));
    expect(within(notes).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(notes).getByText('SEC_B EU Equity')).toBeInTheDocument();
  });

  it('keeps highlight panel and table on the same severity', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    expect((await screen.findAllByText('1 alert(s)')).length).toBeGreaterThan(0);
    fireEvent.click(marketChip('US'));
    const volatility = screen.getByRole('group', { name: 'Volatility' });
    expect(within(volatility).getByText('Warning')).toBeInTheDocument();
    expect(within(volatility).getByText('daily 28.9% / intraday 0.23%')).toBeInTheDocument();
  });

  it('shows missing data as dashes and lists risk notes', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    expect(within(table).getByText('No daily baseline; No intraday bars')).toBeInTheDocument();
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

  it('filters table rows by Exchange with select-all and invert', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    fireEvent.click(within(table).getByRole('button', { name: /Exchange/ }));

    // 筛选面板：两个市场值均默认选中
    expect(screen.getByText(/Filter · Exchange/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Select all' })).toBeInTheDocument();

    // 取消 US → 只剩 EU 行
    fireEvent.click(screen.getByRole('button', { name: 'US' }));
    expect(within(table).queryByText('SEC_A US Equity')).not.toBeInTheDocument();
    expect(within(table).getByText('SEC_B EU Equity')).toBeInTheDocument();

    // 一键反选 → 只剩 US 行
    fireEvent.click(screen.getByRole('button', { name: 'Invert' }));
    expect(within(table).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(table).queryByText('SEC_B EU Equity')).not.toBeInTheDocument();

    // 一键全选 → 恢复两行
    fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
    expect(within(table).getByText('SEC_A US Equity')).toBeInTheDocument();
    expect(within(table).getByText('SEC_B EU Equity')).toBeInTheDocument();
  });

  it('renders filterable headers as buttons and closes the popover on outside click', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const table = await screen.findByRole('table');
    const exchangeButton = within(table).getByRole('button', { name: /Exchange/ });
    expect(exchangeButton).toHaveAttribute('aria-haspopup', 'dialog');

    fireEvent.click(exchangeButton);
    const popover = screen.getByRole('dialog', { name: /Filter Exchange/ });

    // 面板内点击不关闭
    fireEvent.mouseDown(popover);
    expect(screen.getByRole('dialog', { name: /Filter Exchange/ })).toBeInTheDocument();

    // 点击面板外空白处关闭
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('dialog', { name: /Filter Exchange/ })).not.toBeInTheDocument();
  });

  it('collapses and expands all three modules uniformly', async () => {
    stubFetch({ success: true, data: payload });
    renderPanel();

    const notes = await screen.findByRole('group', { name: 'Risk notes' });
    expect(within(notes).getByText('Select a market above to list signals')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Collapse modules' }));
    for (const title of ['Liquidity', 'Volatility', 'Risk notes']) {
      const module = screen.getByRole('group', { name: title });
      expect(within(module).queryByText('Select a market above to list signals')).not.toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Expand modules' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Expand modules' }));
    expect(within(notes).getByText('Select a market above to list signals')).toBeInTheDocument();
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
