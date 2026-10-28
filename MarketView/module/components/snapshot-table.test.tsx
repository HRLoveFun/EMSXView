import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { SnapshotTable } from './snapshot-table';
import type { LiveQuotes, MarketSnapshotRow, MarketStateTickerState } from '../types';

const row: MarketSnapshotRow = {
  equ_ticker: 'SEC_A US Equity',
  trade_date: '20260408',
  daily_close: 99.5,
  daily_volatility: 2.1,
  intraday_volatility: 1.4,
  total_volume: 1_000_000,
  adv_5d: 900_000,
  adv_20d: 2_000_000,
  volume_vs_adv20_pct: 50,
  liquidity_alert: 'none',
  volatility_alert: 'none',
  alert_count: 0,
  market_status: 'open',
  market_time: '10:30',
  alerts: [],
};

const quote: MarketStateTickerState = {
  equ_ticker: 'SEC_A US Equity',
  as_of: '2026-10-27T10:00:00',
  bid: 100.4,
  ask: 100.6,
  last: 100.55,
  high: 101,
  low: 99,
  volume: 123_456,
  spread_bps: 2,
  spread_vs_baseline_bps: null,
  pct_change_1d: -0.456,
  cumulative_volume_ratio: null,
  flags: [],
  schema_version: 'market-state-v2',
};

const names = new Map([['SEC_A US Equity', '甲证券股份有限公司']]);

const renderTable = (live: LiveQuotes) =>
  render(
    <SnapshotTable
      rows={[row]}
      selectedTickers={[]}
      drillTicker={null}
      live={live}
      names={names}
      onToggleTicker={vi.fn()}
      onSelectAll={vi.fn()}
      onClearSelection={vi.fn()}
      onDrillToggle={vi.fn()}
    />,
  );

describe('SnapshotTable live columns (057 DL-15/DL-29)', () => {
  it('renders live last and signed change when quotes are available', () => {
    renderTable({
      byTicker: new Map([['SEC_A US Equity', quote]]),
      status: 'live',
      enabled: true,
      asOf: '2026-10-27T10:00:00',
    });

    expect(screen.getByText('Last')).toBeInTheDocument();
    expect(screen.getByText('Chg %')).toBeInTheDocument();
    // Name 列：中文简称来自 core refdata
    expect(screen.getByText('甲证券股份有限公司')).toBeInTheDocument();
    expect(screen.getByText('100.55')).toBeInTheDocument();
    expect(screen.getByText('-0.46%')).toBeInTheDocument();
  });

  it('falls back to dashes when the live stream is disabled', () => {
    renderTable({ byTicker: new Map(), status: 'idle', enabled: false, asOf: null });

    // Close 与两列实时列都会渲染占位符
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });
});
