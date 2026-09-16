import { useState, useCallback, useEffect, useRef } from 'react';
import type { TradePane } from '@execution/hooks/use-trade-hotkeys';
import type { Order } from '@execution/types';

interface BoardNavigationInput {
  orders: Order[];
  displayedRoutesLength: number;
  selectedOrders: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
}

interface BoardNavigationResult {
  activePane: TradePane;
  setActivePane: (pane: TradePane) => void;
  cursorOrderIdx: number;
  cursorRouteIdx: number;
  moveCursor: (pane: TradePane, delta: number) => void;
  resetCursors: () => void;
}

export function useBoardNavigation({
  orders,
  displayedRoutesLength,
  selectedOrders,
  onSelectionChange,
}: BoardNavigationInput): BoardNavigationResult {
  const [activePane, setActivePane] = useState<TradePane>('orders');
  const [cursorOrderIdx, setCursorOrderIdx] = useState(0);
  const [cursorRouteIdx, setCursorRouteIdx] = useState(0);

  // 列表变短时将光标钳制在有效范围内。
  // 采用渲染期间调整 state 的模式，避免 effect 内同步 setState。
  const [prevOrdersLength, setPrevOrdersLength] = useState(orders.length);
  if (prevOrdersLength !== orders.length) {
    setPrevOrdersLength(orders.length);
    setCursorOrderIdx(i => Math.max(0, Math.min(i, Math.max(0, orders.length - 1))));
  }
  const [prevRoutesLength, setPrevRoutesLength] = useState(displayedRoutesLength);
  if (prevRoutesLength !== displayedRoutesLength) {
    setPrevRoutesLength(displayedRoutesLength);
    setCursorRouteIdx(i => Math.max(0, Math.min(i, Math.max(0, displayedRoutesLength - 1))));
  }

  const moveCursor = useCallback((pane: TradePane, delta: number) => {
    if (pane === 'orders') {
      setCursorOrderIdx(i => {
        const n = orders.length;
        if (n === 0) return 0;
        return Math.max(0, Math.min(n - 1, i + delta));
      });
    } else if (pane === 'routes') {
      setCursorRouteIdx(i => {
        const n = displayedRoutesLength;
        if (n === 0) return 0;
        return Math.max(0, Math.min(n - 1, i + delta));
      });
    }
  }, [orders.length, displayedRoutesLength]);

  const prevCursorRef = useRef<number | null>(null);
  useEffect(() => {
    if (activePane !== 'orders') return;
    if (prevCursorRef.current === null) {
      prevCursorRef.current = cursorOrderIdx;
      return;
    }
    if (prevCursorRef.current === cursorOrderIdx) return;
    prevCursorRef.current = cursorOrderIdx;
    const target = orders[cursorOrderIdx];
    if (!target) return;
    if (selectedOrders.size > 1) return;
    const next = new Set<string>([target.id]);
    if (selectedOrders.size !== 1 || !selectedOrders.has(target.id)) {
      onSelectionChange(next);
    }
  }, [cursorOrderIdx, activePane, onSelectionChange, orders, selectedOrders]);

  useEffect(() => {
    const pane = activePane;
    const idx = pane === 'orders' ? cursorOrderIdx : cursorRouteIdx;
    const scope = pane === 'orders'
      ? document.querySelector('[aria-label="Orders"]')
      : document.querySelector('[aria-label="Routes"]');
    if (!scope) return;
    const rows = scope.querySelectorAll('tbody tr');
    const el = rows[idx] as HTMLElement | undefined;
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activePane, cursorOrderIdx, cursorRouteIdx]);

  const resetCursors = useCallback(() => {
    setCursorOrderIdx(0);
    setCursorRouteIdx(0);
  }, []);

  return {
    activePane,
    setActivePane,
    cursorOrderIdx,
    cursorRouteIdx,
    moveCursor,
    resetCursors,
  };
}
