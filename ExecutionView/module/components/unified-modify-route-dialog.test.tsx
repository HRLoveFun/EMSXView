/**
 * T10 契约测试：UnifiedModifyRouteDialog 的表单（含 orig* 基线）初值取自 route，
 * 「打开 / 切换路由」的重置由调用方以 key 重挂载实现（不再用 effect 回填）。
 *
 * 对应 docs/archive/2026-09-21/021-t10-form-reset-refactor；若有人把回填改回 effect（或去掉 RouteTable 的 key），
 * 这两条会失败。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@execution/services/execution-api', () => ({
  apiService: {
    getRouteEnums: vi.fn().mockResolvedValue({ success: true, data: { orderTypes: [], tifOptions: [] } }),
    getBrokerStrategies: vi.fn().mockResolvedValue({ success: true, data: { strategies: [] } }),
    getMarketBrokerMapping: vi.fn().mockResolvedValue({ success: true, data: { rosters: {} } }),
  },
  cachedApiService: {
    resolveAssetClass: vi.fn().mockResolvedValue('EQTY'),
    getBrokerStrategies: vi.fn().mockResolvedValue({ success: true, data: { strategies: [] } }),
    getBrokerStrategyInfo: vi.fn().mockResolvedValue({ success: true, data: { fields: [] } }),
  },
}));

import { UnifiedModifyRouteDialog } from './unified-modify-route-dialog';
import type { Route } from '@execution/types';

const makeRoute = (id: string, amount: number, ticker: string): Route =>
  ({
    id,
    amount,
    ticker,
    orderType: 'LIMIT',
    limitPrice: 12.5,
    stopPrice: null,
    tif: 'DAY',
    broker: 'BROKER_A',
    strategyType: 'VWAP',
    notes: '',
    status: 'WORKING',
  }) as unknown as Route;

function renderDialog(route: Route, key: string) {
  return render(
    <UnifiedModifyRouteDialog
      key={key}
      open
      route={route}
      onOpenChange={() => {}}
      onSubmit={async () => {}}
    />,
  );
}

describe('UnifiedModifyRouteDialog（T10：key 重挂载式表单重置）', () => {
  it('打开时以 route 原值预填（Qty 等字段）', () => {
    renderDialog(makeRoute('r1', 100, 'AAPL'), 'r1:open');
    expect(screen.getByDisplayValue('100')).toBeInTheDocument();
    expect(screen.getByDisplayValue('12.5')).toBeInTheDocument();
  });

  it('切换路由（调用方 key 变化）后表单回到新路由的原值', () => {
    const { rerender } = renderDialog(makeRoute('r1', 100, 'AAPL'), 'r1:open');
    expect(screen.getByDisplayValue('100')).toBeInTheDocument();

    rerender(
      <UnifiedModifyRouteDialog
        key="r2:open"
        open
        route={makeRoute('r2', 250, 'MSFT')}
        onOpenChange={() => {}}
        onSubmit={async () => {}}
      />,
    );
    expect(screen.getByDisplayValue('250')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('100')).toBeNull();
  });
});
