import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { TickerDetailDrawer } from './ticker-detail-drawer';
import type { TickerDetailPayload } from '../types';

const detail: TickerDetailPayload = {
  equ_ticker: 'SEC_A US Equity',
  trade_date: '20261027',
  bucket_minutes: 10,
  market_code: 'US',
  session_open: '09:30',
  session_close: '16:00',
  session_note: '常规交易时段',
  buckets: [
    {
      index: 0,
      label: '09:30',
      volume: 100,
      cumulative_volume: 100,
      cumulative_pct: 0.5,
      vwap: 190,
      open: 189,
      high: 191,
      low: 188,
      close: 190,
      gap: false,
    },
    {
      index: 1,
      label: '09:40',
      volume: null,
      cumulative_volume: null,
      cumulative_pct: null,
      vwap: null,
      open: null,
      high: null,
      low: null,
      close: null,
      gap: true,
    },
  ],
  prev_buckets: [
    { index: 0, label: '09:30', cumulative_volume: 80, cumulative_pct: 0.4 },
    { index: 1, label: '09:40', cumulative_volume: 160, cumulative_pct: 0.8 },
  ],
  prev_days: 5,
  prev_dates: ['20261026'],
  ohlc: { open: 189, high: 191, low: 188, close: 190 },
  prev_close: 188,
  price_low: 187.5,
  price_high: 191.5,
  price_bin_count: 12,
  cells: [{ bucket: 0, price_bin: 3, volume: 100 }],
  total_volume: 200,
  prev_avg_volume: 200,
  gaps: ['09:40'],
  source: 'bars',
};

const jsonResponse = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

afterEach(() => {
  vi.unstubAllGlobals();
});

const setup = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse({ success: true, data: detail })),
  );
  const onClose = vi.fn();
  render(<TickerDetailDrawer ticker="SEC_A US Equity" onClose={onClose} />);
  return { onClose };
};

describe('TickerDetailDrawer', () => {
  it('renders the shared-axis summary', async () => {
    setup();
    expect(await screen.findByText(/20261027 · 2 buckets/)).toBeInTheDocument();
    expect(screen.getByText(/Prev close/)).toBeInTheDocument();
  });

  it('closes when clicking the blank area outside the drawer', async () => {
    const { onClose } = setup();
    const dialog = await screen.findByRole('dialog');

    // 面板内部点击不关闭
    fireEvent.mouseDown(dialog.firstElementChild as Element);
    expect(onClose).not.toHaveBeenCalled();

    // 点击抽屉外空白（遮罩本身）关闭
    fireEvent.mouseDown(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
