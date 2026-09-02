import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { FilterBar } from './filter-bar';
import type { MarketSnapshotRequest, MarketStockPool } from '../types';

const pools: MarketStockPool[] = [
  {
    pool_id: 'all',
    label: 'Full Snapshot',
    description: 'Latest Stage 7 universe for the selected trade date.',
    default_sort_by: 'total_volume',
    default_sort_direction: 'desc',
  },
  {
    pool_id: 'liquidity-screen',
    label: 'Liquidity Screen',
    description: 'High-ADV instruments only.',
    default_sort_by: 'adv_20d',
    default_sort_direction: 'desc',
  },
];

const baseQuery: MarketSnapshotRequest = {
  limit: 40,
  pool_id: 'all',
  liquidity_alert: 'all',
  volatility_alert: 'all',
  sort_by: 'total_volume',
  sort_direction: 'desc',
};

const setup = (query: MarketSnapshotRequest = baseQuery) => {
  const onPoolChange = vi.fn();
  const onQueryChange = vi.fn();
  const onReset = vi.fn();

  render(
    <FilterBar
      query={query}
      pools={pools}
      activePoolDescription={null}
      onPoolChange={onPoolChange}
      onQueryChange={onQueryChange}
      onReset={onReset}
    />,
  );

  return { onPoolChange, onQueryChange, onReset };
};

describe('FilterBar', () => {
  it('renders every pool as a toggle button', () => {
    setup();

    expect(screen.getByRole('button', { name: 'Full Snapshot' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Liquidity Screen' })).toBeInTheDocument();
  });

  it('delegates pool switching to the parent handler', () => {
    const { onPoolChange } = setup();

    fireEvent.click(screen.getByRole('button', { name: 'Liquidity Screen' }));
    expect(onPoolChange).toHaveBeenCalledWith('liquidity-screen');
  });

  it('renders the backend YYYYMMDD trade date as a date input value', () => {
    setup({ ...baseQuery, trade_date: '20260422' });

    expect((screen.getByLabelText('Trade Date') as HTMLInputElement).value).toBe('2026-04-22');
  });

  it('converts a picked date back to YYYYMMDD for the query', () => {
    const { onQueryChange } = setup();

    fireEvent.change(screen.getByLabelText('Trade Date'), { target: { value: '2026-09-02' } });
    expect(onQueryChange).toHaveBeenCalledWith('trade_date', '20260902');
  });

  it('clears the trade date filter when the input is emptied', () => {
    const { onQueryChange } = setup({ ...baseQuery, trade_date: '20260902' });

    fireEvent.change(screen.getByLabelText('Trade Date'), { target: { value: '' } });
    expect(onQueryChange).toHaveBeenCalledWith('trade_date', undefined);
  });

  it('parses numeric thresholds into numbers', () => {
    const { onQueryChange } = setup();

    fireEvent.change(screen.getByLabelText('Min ADV 20D'), { target: { value: '10000000' } });
    expect(onQueryChange).toHaveBeenCalledWith('min_adv_20d', 10000000);
  });

  it('clears numeric thresholds on empty input', () => {
    // 从已有阈值出发：受控 input 需要值真正发生变化才会触发 React onChange
    const { onQueryChange } = setup({ ...baseQuery, min_adv_20d: 10000000 });

    fireEvent.change(screen.getByLabelText('Min ADV 20D'), { target: { value: '' } });
    expect(onQueryChange).toHaveBeenCalledWith('min_adv_20d', undefined);
  });

  it('delegates the reset action', () => {
    const { onReset } = setup();

    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
