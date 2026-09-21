/**
 * T10 契约测试：RoutePlanDialog 的表单初值取自 editPlan，
 * 「打开 / 切换编辑目标」的重置由调用方以 key 重挂载实现（不再用 effect 回填）。
 *
 * 对应 docs/archive/2026-09-21/021-t10-form-reset-refactor；若有人把回填改回 effect（或去掉调用方 key），
 * 这两条会失败。
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@execution/services/execution-api', () => ({
  apiService: {
    getMarketBrokerMapping: vi.fn().mockResolvedValue({ success: true, data: { rosters: {} } }),
    getRoutePlans: vi.fn().mockResolvedValue({ success: true, data: [] }),
  },
  cachedApiService: {
    getBrokerStrategyInfo: vi.fn().mockResolvedValue({ success: true, data: { fields: [] } }),
  },
}));

import { RoutePlanDialog } from './route-plan-manager';
import type { RoutePlan } from '@execution/types';

const makePlan = (id: number, name: string): RoutePlan =>
  ({
    id,
    name,
    matchMarket: 'US',
    matchSide: 'BOTH',
    activationMode: 'MANUAL',
    splitType: 'BROKER_SPLIT',
    scheduleType: 'TWAP',
    numSlices: 10,
    defaultEndTimeLocal: '16:00',
    allocations: [],
  }) as unknown as RoutePlan;

function renderDialog(plan: RoutePlan | null, key: string) {
  return render(
    <RoutePlanDialog
      key={key}
      open
      onOpenChange={() => {}}
      editPlan={plan}
      onSaved={() => {}}
    />,
  );
}

describe('RoutePlanDialog（T10：key 重挂载式表单重置）', () => {
  it('编辑既有计划时以该计划的值预填', () => {
    renderDialog(makePlan(1, 'Plan Alpha'), '1:open');
    expect(screen.getByDisplayValue('Plan Alpha')).toBeInTheDocument();
  });

  it('新建（editPlan=null）时用默认值，不留上一次的输入', () => {
    renderDialog(null, 'new:open');
    expect(screen.queryByDisplayValue('Plan Alpha')).toBeNull();
  });

  it('切换编辑目标（调用方 key 变化）后表单回到新目标的值', () => {
    const { rerender } = renderDialog(makePlan(1, 'Plan Alpha'), '1:open');
    expect(screen.getByDisplayValue('Plan Alpha')).toBeInTheDocument();

    rerender(
      <RoutePlanDialog
        key="2:open"
        open
        onOpenChange={() => {}}
        editPlan={makePlan(2, 'Plan Beta')}
        onSaved={() => {}}
      />,
    );
    expect(screen.getByDisplayValue('Plan Beta')).toBeInTheDocument();
    expect(screen.queryByDisplayValue('Plan Alpha')).toBeNull();
  });
});
