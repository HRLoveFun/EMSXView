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
import { describe, expect, it } from 'vitest';

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

    // toggleBroker 受「交易所-券商映射」约束：取一个对该订单合法的券商
    const broker =
      result.current.allBrokers.find(b => result.current.isBrokerAllowedFor(b, order))
      ?? result.current.allBrokers[0];

    act(() => result.current.toggleBroker(broker));
    expect(result.current.selectedBrokers).toContain(broker);
    expect(result.current.rows['o1'].allocations[broker]).toMatchObject({ qty: '0' });

    act(() => result.current.toggleBroker(broker));
    expect(result.current.rows['o1'].allocations[broker]).toBeUndefined();

    // 换一批订单后：新行 allocations 默认为空 —— 当前实现下，槽位只在
    // selectedBrokers 变化（而非 orders 变化）时补齐（派生化重构时可一并修正）
    act(() => result.current.toggleBroker(broker));
    rerender({ orders: [makeOrder('o1'), makeOrder('o2')], open: true });
    expect(result.current.rows['o2'].allocations).toEqual({});

    // 再次切换 broker 触发补槽：此时新、旧行都应拿到该 broker 的槽
    act(() => result.current.toggleBroker(broker));
    act(() => result.current.toggleBroker(broker));
    expect(result.current.rows['o1'].allocations[broker]).toMatchObject({ qty: '0' });
    expect(result.current.rows['o2'].allocations[broker]).toMatchObject({ qty: '0' });
  });

  it('open=false：不做对账（行状态保持上一次）', async () => {
    const { result, rerender } = renderState([makeOrder('o1')], true);
    expect(result.current.rows['o1']).toBeDefined();

    rerender({ orders: [makeOrder('o1'), makeOrder('o2')], open: false });
    // 关闭时不补新行（对账守卫），重新打开后才初始化
    expect(Object.keys(result.current.rows)).toEqual(['o1']);
  });
});
