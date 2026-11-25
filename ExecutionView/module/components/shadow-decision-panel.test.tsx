import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { apiFetch } from '@execution/services/execution-api';
import { ShadowDecisionPanel } from './shadow-decision-panel';

vi.mock('@execution/services/execution-api', () => ({
  apiFetch: vi.fn(),
}));

const record = {
  decision_id: 'd1',
  order_id: 'O-1',
  as_of: '2026-11-25T10:00:00+00:00',
  source: 'ENGINE',
  schema_version: 'routing-decision-v2',
  payload: {
    candidates: [
      {
        broker: 'EQ-AAA',
        quantity: 600,
        participation_pct: 0.1,
        strategy_params: { PctVol: '15' },
      },
    ],
    actual_routes: [
      { route_id: '11', broker: 'EQ-AAA', quantity: 600, status: 'WORKING' },
    ],
    rewrite_reason: 'UNCLASSIFIED',
    source: 'ENGINE',
    quote_spread_bps: 12.5,
    constraint_violations: [{ code: 'X', severity: 'BLOCK', message: 'test' }],
  },
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('ShadowDecisionPanel', () => {
  it('renders suggested vs actual side by side', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      success: true,
      data: { records: [record] },
    });

    render(<ShadowDecisionPanel orderId="O-1" />);

    expect(await screen.findByText('Suggested')).toBeTruthy();
    expect(screen.getByText('Actual')).toBeTruthy();
    expect(screen.getAllByText('EQ-AAA').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('UNCLASSIFIED')).toBeTruthy();
    expect(screen.getByText(/spread 12\.50 bps/)).toBeTruthy();
    expect(screen.getByText('BLOCK X')).toBeTruthy();
  });

  it('shows an empty state when no decision exists', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      success: true,
      data: { records: [] },
    });

    render(<ShadowDecisionPanel orderId="O-2" />);

    expect(await screen.findByText('No shadow decision for this order.')).toBeTruthy();
  });

  it('asks for a single order when none is selected', () => {
    render(<ShadowDecisionPanel orderId={null} />);
    expect(screen.getByText(/Select exactly one order/)).toBeTruthy();
  });

  it('degrades to an error message when the API fails', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      success: false,
      error: 'store unavailable',
    });

    render(<ShadowDecisionPanel orderId="O-3" />);

    expect(await screen.findByText('store unavailable')).toBeTruthy();
  });
});
