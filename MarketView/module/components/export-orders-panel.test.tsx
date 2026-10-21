import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { ExportOrdersPanel } from './export-orders-panel';
import type {
  ExportOrderRow,
  OrderIntent,
  OrderIntentBenchmark,
  PreTradeOrdersPayload,
  UnmatchedOrder,
} from '../types';

const makeIntent = (benchmark: OrderIntentBenchmark, closePct: number | null): OrderIntent => ({
  order_key: benchmark === 'UNMAPPED' ? '' : '^7000001^0',
  benchmark,
  close_pct: closePct,
  raw_note: benchmark === 'UNMAPPED' ? 'FOO^7000005^0' : '^7000001^0',
  intent_source: 'emsx-export',
  valid_from: '2026-10-21T02:30:00+00:00',
  export_ts: '2026-10-21T02:30:00+00:00',
  unmatched_reason: benchmark === 'UNMAPPED' ? 'unknown_prefix' : null,
});

const makeRow = (code: string, benchmark: OrderIntentBenchmark, closePct: number | null): ExportOrderRow => ({
  code,
  exch_code: 'EX_A',
  name: `虚构公司${code}`,
  side: 'Sell',
  qty: 100000,
  ccy: 'HKD',
  status: 'Working',
  fill_qty: 50000,
  pct_filled: 50,
  q_pct_5d_adv: 1.67,
  q_pct_tdy: 48.49,
  rem_bal_pct_avg_cls_auct_vol: 10.6,
  working_val_usd: 500000,
  value_usd: 500000,
  chg_pct_dtdy: -8.04,
  last_px_vs_vwap_bps: -16.01,
  earn_rpt_time: null,
  ex_dvd_flag: 'N',
  brkr_code: 'BRK_X',
  create_time: '10:29:01',
  pm_note: makeIntent(benchmark, closePct).raw_note,
  intent: makeIntent(benchmark, closePct),
  extra_fields: { 'Mkt Stat': 'ACTV' },
});

const buildPayload = (): PreTradeOrdersPayload => ({
  exported_at: '2026-10-21T02:30:00+00:00',
  export_file_name: 'emsx_orders_20261021.csv',
  order_count: 3,
  intent_coverage_pct: 66.67,
  intent_mapping_version: 'emsx-pm-note-v1',
  orders: [
    makeRow('SEC_A', 'VWAP', null),
    makeRow('SEC_B', 'MIX', 80),
    makeRow('SEC_C', 'UNMAPPED', null),
  ],
  unmatched: [{ code: 'SEC_C', pm_note: 'FOO^7000005^0', reason: 'unknown_prefix' } satisfies UnmatchedOrder],
});

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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ExportOrdersPanel', () => {
  it('renders export meta, order rows and intent badges', async () => {
    stubFetch(buildPayload());

    render(<ExportOrdersPanel />);

    expect(await screen.findByText('emsx_orders_20261021.csv')).toBeInTheDocument();
    expect(screen.getByText('3 orders')).toBeInTheDocument();
    expect(screen.getByText('Intent coverage 66.7%')).toBeInTheDocument();
    expect(screen.getByText('1 unmatched')).toBeInTheDocument();
    expect(screen.getByText('Mapping emsx-pm-note-v1')).toBeInTheDocument();
    expect(screen.getByText('VWAP')).toBeInTheDocument();
    expect(screen.getByText('MIX 80% @Close')).toBeInTheDocument();
    expect(screen.getByText('SEC_A')).toBeInTheDocument();
  });

  it('lists unmatched intents with readable reasons', async () => {
    stubFetch(buildPayload());

    render(<ExportOrdersPanel />);

    expect(await screen.findByText('Unmatched intents (manual follow-up)')).toBeInTheDocument();
    expect(screen.getByText('SEC_C: Unknown instruction prefix')).toBeInTheDocument();
  });

  it('shows guidance when no export is available', async () => {
    stubFetch({
      exported_at: '',
      export_file_name: '',
      order_count: 0,
      intent_coverage_pct: 0,
      intent_mapping_version: '',
      orders: [],
      unmatched: [],
    });

    render(<ExportOrdersPanel />);

    expect(await screen.findByText(/No EMSX export available/)).toBeInTheDocument();
  });

  it('surfaces fetch failures as an error banner', async () => {
    stubFetch({ detail: 'bad export' }, false);

    render(<ExportOrdersPanel />);

    await waitFor(() => {
      expect(screen.getByText(/bad export/)).toBeInTheDocument();
    });
  });
});
