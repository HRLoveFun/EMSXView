import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TcaOrderTable } from '../components/TcaOrderTable';
import { createDefaultCostViewConfig } from '../lib/thresholds';
import type { TcaReport, TcaRouteSummary } from '../types';

// ── 测试数据 ──

/** 路由工厂：默认 VWAP 单路由；F1 场景只需覆盖 amount / fill / p_avg */
function createRoute(overrides: Partial<TcaRouteSummary> = {}): TcaRouteSummary {
  return {
    order_id: 'O1',
    route_id: 'R1',
    order_as_of_date: '20261104',
    exchange: 'US',
    account: null,
    equ_ticker: 'NVR US Equity',
    currency: 'USD',
    side: 'BUY',
    amount: 10,
    route_shares: 10,
    type: null,
    limit_price: null,
    stop_price: null,
    broker: 'BROKER-A',
    strategy_type: null,
    algo: 'VWAP',
    trader_name: 'Trader',
    fill_count: 1,
    fill: 10,
    fill_continuous: 10,
    fill_close: 0,
    par_rate: 0.01,
    par_rate_continuous: 0.01,
    par_rate_close: 0,
    p_avg: 8178,
    p_avg_continuous: 8178,
    pnl_vwap: -30,
    pnl_vwap_continuous: -30,
    rpm: 0.3,
    rpm_continuous: 0.3,
    pwp_5: null,
    pwp_10: null,
    pwp_15: null,
    pwp_20: null,
    pwp_25: null,
    time_series: [],
    ...overrides,
  };
}

function createReport(orders: TcaRouteSummary[]): TcaReport {
  return {
    filters: { aggregation: 'per_order', limit: 50, offset: 0 },
    total_orders: orders.length,
    offset: 0,
    limit: 50,
    generated_at: '2026-11-04T09:30:00.000Z',
    orders,
  };
}

function renderTable(orders: TcaRouteSummary[]) {
  render(
    <TcaOrderTable
      config={createDefaultCostViewConfig()}
      report={createReport(orders)}
      selectedRouteKey={null}
      onPageChange={() => {}}
      onSelectRoute={() => {}}
    />,
  );
}

// ── F1（210 §0.2）：Amount 是委托股数，金额列 = fill × p_avg ──

describe('TcaOrderTable 成交金额口径', () => {
  it('金额列显示 fill × p_avg，不把 Amount（委托股数）按货币渲染', () => {
    renderTable([createRoute()]);

    // fill 10 × p_avg 8,178 = 81,780 → USD 81.8K；Amount=10 不得显示成 USD 10
    expect(screen.getByText('USD 81.8K')).toBeInTheDocument();
    expect(screen.queryByText('USD 10')).not.toBeInTheDocument();
  });

  it('委托股数单独成列（Amount 原值）', () => {
    renderTable([createRoute({ amount: 500_000 })]);

    expect(screen.getByText('委托股数')).toBeInTheDocument();
    expect(screen.getByTitle('委托股数（Amount）')).toHaveTextContent('500,000');
  });

  it('Amount 再大也不影响金额判定（成交额只看 fill × p_avg）', () => {
    renderTable([createRoute({ amount: 500_000, route_shares: 10, fill: 10, p_avg: 10 })]);

    // 成交额 = 10 × 10 = 100；Amount=500,000 股不得被当作金额
    expect(screen.getByText('USD 100')).toBeInTheDocument();
    expect(screen.queryByText('USD 500.0K')).not.toBeInTheDocument();
  });

  it('零成交路由金额为 0，不退回委托股数', () => {
    renderTable([createRoute({ amount: 5_000, route_shares: 5_000, fill: 0 })]);

    expect(screen.getByText('USD 0')).toBeInTheDocument();
    expect(screen.queryByText('USD 5.0K')).not.toBeInTheDocument();
  });

  it('缺 p_avg 时金额显示 —，不回落 Amount', () => {
    renderTable([createRoute({ p_avg: null })]);

    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('USD 10')).not.toBeInTheDocument();
  });

  it('成交额为无符号量，不渲染成 +81.8K（非盈亏差额）', () => {
    renderTable([createRoute()]);

    expect(screen.getByText('USD 81.8K')).toBeInTheDocument();
    expect(screen.queryByText('USD +81.8K')).not.toBeInTheDocument();
  });

  it('USD 列不在前端重算汇率（后端未下发 USD 成交额时显示 —）', () => {
    // 即使 payload 带了 fx_rate（未来后端可能加），也不在前端换算：
    // GBp/ILs/ZAr 小计价单位与 USD 兜底只有后端口径能正确处理。
    renderTable([createRoute({ fx_rate: 1.3 })]);

    const usdCell = screen.getByTitle('后端未下发逐路由 USD 成交额');
    expect(usdCell).toHaveTextContent('—');
  });
});

// ── CCP-20261112：adv_20d / daily_volatility 可空，NULL 显示 —（禁止当 0） ──

describe('TcaOrderTable 流动性 / 波动率列', () => {
  it('展示 ADV 20d（shares）与年化波动率（百分比）', () => {
    renderTable([createRoute({ adv_20d: 4_600_000, daily_volatility: 26 })]);

    expect(screen.getByText('4,600,000')).toBeInTheDocument();
    expect(screen.getByText('26.0%')).toBeInTheDocument();
  });

  it('两列为 null 时显示 —，不渲染 0 / 0%', () => {
    renderTable([createRoute({ adv_20d: null, daily_volatility: null })]);

    const missingCells = screen.getAllByTitle('行情未就绪');
    expect(missingCells).toHaveLength(2);
    for (const cell of missingCells) {
      expect(cell).toHaveTextContent('—');
      expect(cell).not.toHaveTextContent('0');
    }
  });
});
