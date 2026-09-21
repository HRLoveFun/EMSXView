/**
 * useBatchRouteState 契约测试（specs/023 —— T12 前置：先补测试网，再做 rows 派生化重构）。
 *
 * 锁定「父级订单列表刷新后与行状态对账」的当前语义：
 *   1. 打开对话框 ⇒ 每个订单一行且默认 selected=true
 *   2. 列表新增订单 ⇒ 补行，默认 selected=false（不影响既有行）
 *   3. 列表移除订单 ⇒ 该行剔除
 *   4. 用户的选中/分配改动在列表刷新后保留（对账只做增删，不覆盖）
 *   5. 选中 broker ⇒ 每行补齐该 broker 的分配槽；取消 ⇒ 槽移除
 *   6. open=false 时不做对账
 */
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

// 券商目录来自后端（缺失时 allBrokers 为空）——测试提供确定性目录，
// 否则「选中券商」类用例会退化为拿 undefined 当券商（023 曾如此）
vi.mock('@execution/hooks/use-broker-algorithms', () => ({
  useBrokerAlgorithms: () => ({
    configs: [
      { broker: 'B1', strategies: [{ name: 'S1' }] },
      { broker: 'B2', strategies: [{ name: 'S2' }] },
    ],
  }),
}));
vi.mock('@execution/hooks/use-market-broker-mapping', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@execution/hooks/use-market-broker-mapping')>();
  return {
    ...actual,
    useMarketBrokerMapping: () => ({ allowedFor: () => null }),   // null = 未配置 ⇒ 全部允许
  };
});

import type { Order } from '@execution/types';
import { useBatchRouteState } from './use-batch-route-state';

function makeOrder(id: string, quantity = 1000): Order {
  return {
    id,
    symbol: 'TEST',
    side: 'BUY',
    status: 'WORKING',
    orderType: 'LIMIT',
    quantity,
    filledQuantity: 0,
    remainingQuantity: quantity,
    price: 10,
    timeInForce: 'DAY',
    account: 'acct',
    portfolio: 'pf',
    trader: 'trader',
    createdAt: '2026-09-01T00:00:00Z',
    updatedAt: '2026-09-01T00:00:00Z',
    exchange: 'US',
    currency: 'USD',
    customNote1: '',
    customNote2: '',
    customNote3: '',
  } as unknown as Order;
}

function renderState(orders: Order[], open = true) {
  return renderHook(
    ({ orders: list, open: isOpen }: { orders: Order[]; open: boolean }) =>
      useBatchRouteState({
        orders: list,
        open: isOpen,
        onOpenChange: () => {},
        onComplete: () => {},
      }),
    { initialProps: { orders, open } },
  );
}

describe('useBatchRouteState —— 行状态对账', () => {
  it('打开对话框：每个订单一行，默认选中', async () => {
    const { result, rerender } = renderState([makeOrder('o1'), makeOrder('o2')], false);

    rerender({ orders: [makeOrder('o1'), makeOrder('o2')], open: true });

    expect(Object.keys(result.current.rows).sort()).toEqual(['o1', 'o2']);
    expect(result.current.rows['o1'].selected).toBe(true);
    expect(result.current.rows['o2'].selected).toBe(true);
    expect(result.current.selectedOrders.map(o => o.id)).toEqual(['o1', 'o2']);
  });

  it('列表新增订单：补行且默认未选中，既有行不受影响', async () => {
    const { result, rerender } = renderState([makeOrder('o1')], true);
    expect(result.current.rows['o1'].selected).toBe(true);

    rerender({ orders: [makeOrder('o1'), makeOrder('o2')], open: true });

    expect(result.current.rows['o2']).toBeDefined();
    expect(result.current.rows['o2'].selected).toBe(false);   // 后到的订单默认不选中
    expect(result.current.rows['o1'].selected).toBe(true);     // 既有选中态保留
  });

  it('列表移除订单：该行被剔除', async () => {
    const { result, rerender } = renderState([makeOrder('o1'), makeOrder('o2')], true);

    rerender({ orders: [makeOrder('o1')], open: true });

    expect(result.current.rows['o2']).toBeUndefined();
    expect(result.current.rows['o1']).toBeDefined();
  });

  it('用户改动在列表刷新后保留（对账只增删不覆盖）', async () => {
    const { result, rerender } = renderState([makeOrder('o1'), makeOrder('o2')], true);

    act(() => result.current.patchRow('o1', { selected: false }));
    act(() => result.current.patchAlloc('o2', 'BROKER_A', { qty: '7' }));
    expect(result.current.rows['o1'].selected).toBe(false);

    // 刷新：新增 o3、移除 o2 之外的行均保留
    rerender({ orders: [makeOrder('o1'), makeOrder('o2'), makeOrder('o3')], open: true });

    expect(result.current.rows['o1'].selected).toBe(false);          // 用户取消选中被保留
    expect(result.current.rows['o2'].allocations).toEqual({});       // 见下条：未选 broker 时槽被清
    expect(result.current.rows['o3'].selected).toBe(false);          // 新增行默认不选中
  });

  it('选中 broker：每行补齐分配槽；取消选择后槽移除', async () => {
    const order = makeOrder('o1');
    const { result, rerender } = renderState([order], true);
    const broker = result.current.allBrokers[0];
    expect(broker).toBeTruthy();

    act(() => result.current.toggleBroker(broker));
    expect(result.current.selectedBrokers).toContain(broker);
    expect(result.current.rows['o1'].allocations[broker]).toMatchObject({ qty: '0' });

    act(() => result.current.toggleBroker(broker));
    expect(result.current.rows['o1'].allocations[broker]).toBeUndefined();

    // 重新勾选 + 列表新增订单：新行也直接带上已选券商的槽
    //（T12 第二步派生化修正了此前「新行要等 selectedBrokers 再变化才补槽」的不对称）
    act(() => result.current.toggleBroker(broker));
    rerender({ orders: [order, makeOrder('o2')], open: true });
    expect(result.current.rows['o2'].allocations[broker]).toMatchObject({ qty: '0' });
  });

  it('关闭对话框：视图仍反映当前订单列表（open 只控制打开时的重置）', async () => {
    const { result, rerender } = renderState([makeOrder('o1')], true);
    expect(Object.keys(result.current.rows)).toEqual(['o1']);

    rerender({ orders: [makeOrder('o1'), makeOrder('o2')], open: false });
    // rows 是 orders × rowState 的派生视图，不受 open 影响；且不写入 state（无级联渲染）
    expect(Object.keys(result.current.rows).sort()).toEqual(['o1', 'o2']);
    expect(result.current.rows['o2'].selected).toBe(false);
  });
});
