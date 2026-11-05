import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TraderFilterBar } from '../components/trader/TraderFilterBar';
import { INITIAL_TRADER_FILTERS } from '../lib/trader-filters';
import type { TraderFilterState } from '../types';

// ── 市场筛选（2026-11-05）：位于结束日期与交易员之间 ──

const OPTIONS = {
  traders: ['HRCHEN'],
  strategy_types: ['VWAP'],
  symbols: ['ABCD US Equity'],
  brokers: ['BROKER_A'],
  algos: ['vwap'],
  exchanges: ['HK', 'LN', 'US'],
};

function renderBar(overrides: Partial<TraderFilterState> = {}) {
  const onChange = vi.fn();
  render(
    <TraderFilterBar
      state={{ ...INITIAL_TRADER_FILTERS, ...overrides }}
      options={OPTIONS}
      onChange={onChange}
      onRefresh={() => {}}
    />,
  );
  return { onChange };
}

describe('TraderFilterBar 市场筛选', () => {
  it('市场控件位于结束日期之后、交易员之前', () => {
    renderBar();

    const endDate = screen.getByLabelText('结束日期');
    const market = screen.getByRole('button', { name: '市场' });
    const trader = screen.getByRole('button', { name: '交易员' });

    expect(endDate.compareDocumentPosition(market) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
    expect(market.compareDocumentPosition(trader) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it('从下拉选取市场 → onChange 回传 exchanges', async () => {
    const user = userEvent.setup();
    const { onChange } = renderBar();

    await user.click(screen.getByRole('button', { name: '市场' }));
    await user.click(screen.getByRole('option', { name: 'LN' }));

    expect(onChange).toHaveBeenCalledWith({ exchanges: ['LN'] });
  });

  it('已选市场进入筛选摘要并可单个移除', async () => {
    const user = userEvent.setup();
    const { onChange } = renderBar({ exchanges: ['LN', 'US'] });

    expect(screen.getByText('市场：LN, US')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '移除 市场：LN, US' }));
    expect(onChange).toHaveBeenCalledWith({ exchanges: [] });
  });
});
