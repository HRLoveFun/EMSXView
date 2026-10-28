import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { IntervalSeriesPayload, Order } from '@execution/types';
import { apiService } from '@execution/services/execution-api';
import { IntervalSeriesPanel } from './IntervalSeriesPanel';

vi.mock('@execution/services/execution-api', () => ({
  apiService: { getIntervalSeries: vi.fn() },
}));

const order = {
  id: '1',
  symbol: 'AAPL',
  exchange: 'US',
  createdAt: '2026-04-08T09:31:00',
  strategyStartTime: '09:30',
  strategyEndTime: '10:00',
  avgPrice: 101,
  arrivalPrice: 100,
} as Order;

const payload: IntervalSeriesPayload = {
  equ_ticker: 'AAPL US Equity',
  trade_date: '20260408',
  start: '09:30:00',
  end: '10:00:00',
  bucket_minutes: 5,
  source: 'formal',
  points: [
    {
      bucket_start: '09:30:00',
      bucket_end: '09:35:00',
      price: 100.5,
      vwap: 100.4,
      volume: 1000,
      cum_volume: 1000,
      is_gap: false,
    },
    {
      bucket_start: '09:35:00',
      bucket_end: '09:40:00',
      price: null,
      vwap: null,
      volume: 0,
      cum_volume: 1000,
      is_gap: true,
    },
  ],
  interval_vwap: 100.4,
  total_volume: 1000,
  bar_count: 12,
  gap_buckets: 1,
  generated_at: '2026-10-27T01:00:00+00:00',
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('IntervalSeriesPanel', () => {
  it('renders summary and gap count', async () => {
    vi.mocked(apiService.getIntervalSeries).mockResolvedValue(payload);

    render(<IntervalSeriesPanel order={order} onClose={() => undefined} />);

    expect(await screen.findByText('source: formal')).toBeInTheDocument();
    expect(screen.getByText('12 bars')).toBeInTheDocument();
    expect(screen.getByText('1 gap bucket(s)')).toBeInTheDocument();
    expect(screen.getByText('AAPL US Equity')).toBeInTheDocument();
  });

  it('explains when the interval has no bars', async () => {
    vi.mocked(apiService.getIntervalSeries).mockResolvedValue({
      ...payload,
      source: 'none',
      points: [],
      interval_vwap: null,
      total_volume: 0,
      bar_count: 0,
      gap_buckets: 0,
    });

    render(<IntervalSeriesPanel order={order} onClose={() => undefined} />);

    expect(await screen.findByText(/区间内无可用 bar/)).toBeInTheDocument();
  });

  it('surfaces fetch failures', async () => {
    vi.mocked(apiService.getIntervalSeries).mockRejectedValue(new Error('network down'));

    render(<IntervalSeriesPanel order={order} onClose={() => undefined} />);

    expect(await screen.findByText('network down')).toBeInTheDocument();
  });
});
