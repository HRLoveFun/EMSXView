import { describe, expect, it } from 'vitest';

import {
  buildMarketCandidatePayload,
  countRowsWithSeverity,
  fromISODateInput,
  toISODateInput,
} from './workspace';
import type { MarketSnapshotPayload } from '../types';

const snapshot: MarketSnapshotPayload = {
  trade_date: '20260422',
  row_count: 2,
  available_pools: [
    {
      pool_id: 'all',
      label: 'Full Snapshot',
      description: 'Latest Stage 7 universe for the selected trade date.',
      default_sort_by: 'total_volume',
      default_sort_direction: 'desc',
    },
  ],
  active_pool_id: 'all',
  filters: {
    min_adv_20d: null,
    min_total_volume: null,
    min_daily_volatility: null,
    min_intraday_volatility: null,
    liquidity_alert: 'all',
    volatility_alert: 'all',
  },
  sort: {
    field: 'total_volume',
    direction: 'desc',
  },
  rows: [
    {
      equ_ticker: 'AAPL US Equity',
      trade_date: '20260422',
      daily_close: 189.25,
      daily_volatility: 22.4,
      intraday_volatility: 1.8,
      total_volume: 105000000,
      adv_5d: 99000000,
      adv_20d: 101500000,
      volume_vs_adv20_pct: 103.45,
      liquidity_alert: 'normal',
      volatility_alert: 'normal',
      alert_count: 0,
      alerts: [],
    },
    {
      equ_ticker: 'TSLA US Equity',
      trade_date: '20260422',
      daily_close: 166.8,
      daily_volatility: 45.2,
      intraday_volatility: 4.1,
      total_volume: 25000000,
      adv_5d: 12000000,
      adv_20d: 8000000,
      volume_vs_adv20_pct: 312.5,
      liquidity_alert: 'warning',
      volatility_alert: 'critical',
      alert_count: 2,
      alerts: [
        {
          code: 'volatility-alert',
          category: 'volatility',
          severity: 'critical',
          message: 'Daily vol 45.2%, intraday vol 4.1%',
        },
      ],
    },
  ],
  candidate_payload: {
    source: 'marketview-candidate-v1',
    handoff_target: 'ExecutionView',
    trade_date: '20260422',
    pool_id: 'all',
    pool_label: 'Full Snapshot',
    filters: {
      min_adv_20d: null,
      min_total_volume: null,
      min_daily_volatility: null,
      min_intraday_volatility: null,
      liquidity_alert: 'all',
      volatility_alert: 'all',
    },
    sort: {
      field: 'total_volume',
      direction: 'desc',
    },
    row_count: 2,
    candidates: [
      {
        equ_ticker: 'AAPL US Equity',
        trade_date: '20260422',
        daily_close: 189.25,
        total_volume: 105000000,
        adv_20d: 101500000,
        daily_volatility: 22.4,
        intraday_volatility: 1.8,
        liquidity_alert: 'normal',
        volatility_alert: 'normal',
        alerts: [],
      },
      {
        equ_ticker: 'TSLA US Equity',
        trade_date: '20260422',
        daily_close: 166.8,
        total_volume: 25000000,
        adv_20d: 8000000,
        daily_volatility: 45.2,
        intraday_volatility: 4.1,
        liquidity_alert: 'warning',
        volatility_alert: 'critical',
        alerts: [
          {
            code: 'volatility-alert',
            category: 'volatility',
            severity: 'critical',
            message: 'Daily vol 45.2%, intraday vol 4.1%',
          },
        ],
      },
    ],
  },
};

describe('MarketView workspace helpers', () => {
  it('reuses the filtered universe payload when there is no explicit selection', () => {
    expect(buildMarketCandidatePayload(snapshot, [])).toBe(snapshot.candidate_payload);
  });

  it('narrows the handoff payload to the explicitly selected tickers', () => {
    const payload = buildMarketCandidatePayload(snapshot, ['TSLA US Equity']);

    expect(payload.row_count).toBe(1);
    expect(payload.candidates[0].equ_ticker).toBe('TSLA US Equity');
    expect(payload.pool_id).toBe('all');
  });

  it('counts rows whose liquidity or volatility state matches the requested severity', () => {
    expect(countRowsWithSeverity(snapshot.rows, 'warning')).toBe(1);
    expect(countRowsWithSeverity(snapshot.rows, 'critical')).toBe(1);
  });
});

describe('MarketView trade date conversion', () => {
  it('converts backend YYYYMMDD dates to date input values', () => {
    expect(toISODateInput('20260422')).toBe('2026-04-22');
  });

  it('returns an empty value for missing or malformed backend dates', () => {
    expect(toISODateInput(undefined)).toBe('');
    expect(toISODateInput(null)).toBe('');
    expect(toISODateInput('')).toBe('');
    expect(toISODateInput('2026042')).toBe('');
    expect(toISODateInput('abcd0422')).toBe('');
  });

  it('converts date input values back to backend YYYYMMDD', () => {
    expect(fromISODateInput('2026-09-02')).toBe('20260902');
  });

  it('yields undefined for empty or malformed date input values', () => {
    expect(fromISODateInput('')).toBeUndefined();
    expect(fromISODateInput('2026-9-2')).toBeUndefined();
    expect(fromISODateInput('20260902')).toBeUndefined();
  });
});