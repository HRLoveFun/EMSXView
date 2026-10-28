import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import {
  fmtCompact,
  fmtNumber,
  fmtPercent,
  getIntentLabel,
  getIntentTone,
  getMarketStatusText,
  getMarketStatusTone,
  getSeverityText,
  getSeverityTone,
  getUnmatchedReasonText,
  isLiveTrading,
  renderMarketStatusBadge,
  renderSeverityBadge,
} from './marketview-utils';
import {
  buildLiveQuotes,
  fmtSignedPercent,
  liveVolumeVsAdvPct,
  pctToneClass,
} from './lib/workspace';
import type { MarketStateSnapshot } from './types';

describe('MarketView format helpers', () => {
  it('formats numbers with fixed digits and dashes for missing values', () => {
    expect(fmtNumber(189.25, 2)).toBe('189.25');
    expect(fmtNumber(null)).toBe('—');
    expect(fmtNumber(undefined)).toBe('—');
  });

  it('formats compact volume notation', () => {
    expect(fmtCompact(105000000)).toBe('105M');
    expect(fmtCompact(null)).toBe('—');
  });

  it('formats percentages with a percent suffix', () => {
    expect(fmtPercent(22.4, 1)).toBe('22.4%');
    expect(fmtPercent(null, 1)).toBe('—');
  });
});

describe('MarketView severity helpers', () => {
  it('maps severity levels to readable text', () => {
    expect(getSeverityText('critical')).toBe('Critical');
    expect(getSeverityText('warning')).toBe('Warning');
    expect(getSeverityText('normal')).toBe('Normal');
    expect(getSeverityText('none')).toBe('N/A');
  });

  it('assigns distinct tones per severity', () => {
    expect(getSeverityTone('critical')).toContain('red');
    expect(getSeverityTone('warning')).toContain('amber');
    expect(getSeverityTone('normal')).toContain('emerald');
    expect(getSeverityTone('none')).toContain('muted');
  });

  it('renders a labelled severity badge', () => {
    render(renderSeverityBadge('Liquidity', 'critical'));
    expect(screen.getByText('Liquidity: Critical')).toBeInTheDocument();
  });
});

describe('MarketView live quote helpers (057 DL-15/29)', () => {
  const state = {
    equ_ticker: 'AAPL US Equity',
    as_of: '2026-10-27T10:00:00',
    bid: 100,
    ask: 100.2,
    last: 100.1,
    high: 101,
    low: 99,
    volume: 10_000,
    spread_bps: 20,
    spread_vs_baseline_bps: null,
    pct_change_1d: 1.5,
    cumulative_volume_ratio: null,
    flags: [],
    schema_version: 'market-state-v2',
  };
  const snapshot: MarketStateSnapshot = {
    as_of: '2026-10-27T10:00:00',
    enabled: true,
    tickers: [state],
    thresholds: {},
    schema_version: 'market-state-v2',
  };

  it('indexes live quotes by ticker with source status', () => {
    const live = buildLiveQuotes(snapshot, 'live');
    expect(live.enabled).toBe(true);
    expect(live.status).toBe('live');
    expect(live.asOf).toBe('2026-10-27T10:00:00');
    expect(live.byTicker.get('AAPL US Equity')?.last).toBe(100.1);
    expect(live.byTicker.get('MSFT US Equity')).toBeUndefined();
  });

  it('returns an empty index when the backend switch is off', () => {
    const live = buildLiveQuotes({ ...snapshot, enabled: false }, 'idle');
    expect(live.enabled).toBe(false);
    expect(live.byTicker.size).toBe(0);
    expect(buildLiveQuotes(null, 'idle').byTicker.size).toBe(0);
  });

  it('formats signed percentages and tones', () => {
    expect(fmtSignedPercent(1.234)).toBe('+1.23%');
    expect(fmtSignedPercent(-0.456)).toBe('-0.46%');
    expect(fmtSignedPercent(0)).toBe('0.00%');
    expect(fmtSignedPercent(null)).toBe('—');

    expect(pctToneClass(1)).toContain('emerald');
    expect(pctToneClass(-1)).toContain('rose');
    expect(pctToneClass(0)).toContain('muted');
    expect(pctToneClass(null)).toContain('muted');
  });

  it('computes live participation against the daily ADV', () => {
    expect(liveVolumeVsAdvPct(500_000, 2_000_000)).toBe(25);
    expect(liveVolumeVsAdvPct(null, 2_000_000)).toBeNull();
    expect(liveVolumeVsAdvPct(500_000, null)).toBeNull();
    expect(liveVolumeVsAdvPct(500_000, 0)).toBeNull();
  });
});

describe('MarketView trading status helpers (057 DL-29 追加)', () => {
  it('maps statuses to readable text and tones', () => {
    expect(getMarketStatusText('open')).toBe('Trading');
    expect(getMarketStatusText('lunch')).toBe('Lunch');
    expect(getMarketStatusText('pre')).toBe('Pre-open');
    expect(getMarketStatusText('closed')).toBe('Closed');
    expect(getMarketStatusText('unknown')).toBe('Unknown');

    expect(getMarketStatusTone('open')).toContain('emerald');
    expect(getMarketStatusTone('lunch')).toContain('amber');
    expect(getMarketStatusTone('pre')).toContain('sky');
    expect(getMarketStatusTone('closed')).toContain('muted');
  });

  it('only treats open/lunch as live trading', () => {
    expect(isLiveTrading('open')).toBe(true);
    expect(isLiveTrading('lunch')).toBe(true);
    expect(isLiveTrading('pre')).toBe(false);
    expect(isLiveTrading('closed')).toBe(false);
    expect(isLiveTrading('unknown')).toBe(false);
  });

  it('renders a status badge with exchange local time in the tooltip', () => {
    render(renderMarketStatusBadge('closed', '18:00'));
    const badge = screen.getByText('Closed');
    expect(badge).toHaveAttribute('title', expect.stringContaining('18:00'));
  });
});

describe('MarketView intent helpers (057 DL-01)', () => {
  it('labels MIX with its close ratio and other benchmarks verbatim', () => {
    expect(getIntentLabel('MIX', 80)).toBe('MIX 80% @Close');
    expect(getIntentLabel('MIX', null)).toBe('MIX');
    expect(getIntentLabel('CLOSE', 100)).toBe('CLOSE');
    expect(getIntentLabel('UNMAPPED', null)).toBe('UNMAPPED');
  });

  it('assigns distinct tones per benchmark, red for unmapped', () => {
    expect(getIntentTone('VWAP')).toContain('sky');
    expect(getIntentTone('CLOSE')).toContain('indigo');
    expect(getIntentTone('MIX')).toContain('violet');
    expect(getIntentTone('SPECIAL')).toContain('amber');
    expect(getIntentTone('UNMAPPED')).toContain('red');
  });

  it('maps unmatched reason codes to readable text', () => {
    expect(getUnmatchedReasonText('empty_pm_note')).toBe('Empty PM note');
    expect(getUnmatchedReasonText('unknown_prefix')).toBe('Unknown instruction prefix');
    expect(getUnmatchedReasonText('missing_order_key')).toBe('Missing order key (^ segment)');
    // 未知原因码原样透出，不静默吞掉
    expect(getUnmatchedReasonText('future_code')).toBe('future_code');
  });
});
