import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { ListOrdered, GitBranch, Play, X as XIcon, Keyboard, ChevronDown, ChevronRight } from 'lucide-react';
import { OrderTable } from './OrderTable';
import { RouteTable } from './RouteTable';
import { BatchOperationPanel } from './BatchOperationPanel';
import { AlgoLaunchDialog } from '@/components/algo-launch-dialog';
import { SubOrderReviewPanel } from '@/components/sub-order-review-panel';
import { useTradeHotkeys, HotkeyCheatsheet, type TradePane } from '@execution/hooks/use-trade-hotkeys';
import type {
  Order, Route, OrderFilters, BatchUpdateRequest,
  CancelRouteRequest, ModifyRouteRequest, ModifyOrderRequest,
  CreateParentExecutionRequest,
} from '@/types';

interface ExecutionBoardProps {
  orders: Order[];
  allOrders: Order[];
  routes: Route[];
  selectedOrders: Set<string>;
  onSelectionChange: (selectedIds: Set<string>) => void;
  isLoading: boolean;
  filters: OrderFilters;
  onFilterChange: (filters: OrderFilters) => void;
  currentTrader: string;
  onBatchUpdate: (request: BatchUpdateRequest) => Promise<void>;
  onClearSelection: () => void;
  onCancelRoute?: (request: CancelRouteRequest) => Promise<void>;
  onModifyRoute?: (request: ModifyRouteRequest) => Promise<void>;
  onModifyOrder?: (request: ModifyOrderRequest) => Promise<void>;
  onRefresh?: () => Promise<void>;
  onLaunchExecution?: (request: CreateParentExecutionRequest) => Promise<void>;
}

export function ExecutionBoard({
  orders,
  allOrders,
  routes,
  selectedOrders,
  onSelectionChange,
  isLoading,
  filters,
  onFilterChange,
  currentTrader,
  onBatchUpdate,
  onClearSelection,
  onCancelRoute,
  onModifyRoute,
  onModifyOrder,
  onRefresh,
  onLaunchExecution,
}: ExecutionBoardProps) {
  const [algoLaunchOrder] = useState<Order | null>(null);
  const [isAlgoDialogOpen, setIsAlgoDialogOpen] = useState(false);
  const [showSubOrderPanel, setShowSubOrderPanel] = useState(false);
  const [pendingProposalCount, setPendingProposalCount] = useState(0);

  const handleAlgoConfirm = useCallback(async (request: CreateParentExecutionRequest) => {
    if (onLaunchExecution) {
      await onLaunchExecution(request);
    }
  }, [onLaunchExecution]);

  // Count orders with active algo executions
  const algoOrderCount = orders.filter(o => o.parentExecutionId != null).length;

  // ── Order \u2192 Route linkage ─────────────────────────────────────────────
  // When orders are selected in the top pane, filter the Route pane to routes
  // belonging to those orders. Routes are linked to their parent via `sequence`
  // which matches `order.id` (stringified). Clearing selection shows all routes.
  const displayedRoutes = useMemo(() => {
    if (selectedOrders.size === 0) return routes;
    const sequences = new Set<string>();
    for (const id of selectedOrders) sequences.add(String(id));
    return routes.filter(r => sequences.has(String(r.sequence)));
  }, [routes, selectedOrders]);

  const selectedOrderCount = selectedOrders.size;
  const isRouteFiltered = selectedOrderCount > 0;

  // ── Keyboard flow ─────────────────────────────────────────────────────
  const [activePane, setActivePane] = useState<TradePane>('orders');
  // Cursor indices for j/k navigation in each pane
  const [cursorOrderIdx, setCursorOrderIdx] = useState(0);
  const [cursorRouteIdx, setCursorRouteIdx] = useState(0);

  // Clamp cursor indices when underlying lists change
  useEffect(() => {
    if (cursorOrderIdx >= orders.length) setCursorOrderIdx(Math.max(0, orders.length - 1));
  }, [orders.length, cursorOrderIdx]);
  useEffect(() => {
    if (cursorRouteIdx >= displayedRoutes.length) setCursorRouteIdx(Math.max(0, displayedRoutes.length - 1));
  }, [displayedRoutes.length, cursorRouteIdx]);

  const moveCursor = useCallback((pane: TradePane, delta: number) => {
    if (pane === 'orders') {
      setCursorOrderIdx(i => {
        const n = orders.length;
        if (n === 0) return 0;
        return Math.max(0, Math.min(n - 1, i + delta));
      });
    } else if (pane === 'routes') {
      setCursorRouteIdx(i => {
        const n = displayedRoutes.length;
        if (n === 0) return 0;
        return Math.max(0, Math.min(n - 1, i + delta));
      });
    }
  }, [orders.length, displayedRoutes.length]);

  // When cursor moves in orders pane, single-select that order so the Route
  // pane filters to its child routes (Bloomberg-style linkage). Only fires
  // on actual cursor movement (keyboard nav) — not on initial mount, and
  // not when the user already has a multi-selection from clicking checkboxes
  // (otherwise this effect would stomp on the user's selection on every
  // data refresh by re-asserting the cursor's single-selection).
  const prevCursorRef = useRef<number | null>(null);
  useEffect(() => {
    if (activePane !== 'orders') return;
    // Skip the very first run after mount so we don't auto-select orders[0].
    if (prevCursorRef.current === null) {
      prevCursorRef.current = cursorOrderIdx;
      return;
    }
    if (prevCursorRef.current === cursorOrderIdx) return;
    prevCursorRef.current = cursorOrderIdx;
    const target = orders[cursorOrderIdx];
    if (!target) return;
    // If the user has a multi-selection (>1) we don't override — they're
    // building a batch. The cursor still moves (and Routes pane keeps using
    // its own filter), but selection is left intact.
    if (selectedOrders.size > 1) return;
    const next = new Set<string>([target.id]);
    if (selectedOrders.size !== 1 || !selectedOrders.has(target.id)) {
      onSelectionChange(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursorOrderIdx, activePane]);

  // Scroll cursor row into view (best-effort; rows tagged with data-cursor-row)
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

  const { cheatsheetOpen, setCheatsheetOpen } = useTradeHotkeys(
    true,
    activePane,
    {
      onCursorDown: (pane) => moveCursor(pane, 1),
      onCursorUp:   (pane) => moveCursor(pane, -1),
      onToggleSelect: (pane) => {
        if (pane === 'orders') {
          const target = orders[cursorOrderIdx];
          if (!target) return;
          const next = new Set(selectedOrders);
          if (next.has(target.id)) next.delete(target.id); else next.add(target.id);
          onSelectionChange(next);
        }
      },
      onEscape: () => {
        if (isRouteFiltered) {
          onClearSelection();
          // Send the cursor back to the top so the next j/k keystroke does not
          // resume from a stale row that may now be invisible after re-filter.
          setCursorOrderIdx(0);
          setCursorRouteIdx(0);
        }
      },
      onFocusSearch: () => {
        // Best-effort: focus the first visible input[aria-label*="Filter"] in the active pane
        const scope = activePane === 'orders'
          ? document.querySelector('[aria-label="Orders"]')
          : document.querySelector('[aria-label="Routes"]');
        const target = scope?.querySelector<HTMLInputElement>('input[type="text"], input:not([type])');
        target?.focus();
      },
    },
    setActivePane,
  );

  return (
    <div className="flex flex-col gap-2 h-[calc(100vh-180px)] min-h-[560px]">
      <HotkeyCheatsheet open={cheatsheetOpen} onClose={() => setCheatsheetOpen(false)} />
      {/* ── Linkage status bar ───────────────────────────────────────── */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground px-1 shrink-0">
        <span className="flex items-center gap-1"><ListOrdered className="h-3.5 w-3.5" />Orders: <span className="font-semibold text-foreground">{orders.length}</span></span>
        <span className="text-border">|</span>
        <span className="flex items-center gap-1">
          <GitBranch className="h-3.5 w-3.5" />
          Routes: <span className="font-semibold text-foreground">{displayedRoutes.length}</span>
          {isRouteFiltered && (
            <span className="text-[10px] text-muted-foreground">(of {routes.length}, filtered by {selectedOrderCount} selected order{selectedOrderCount === 1 ? '' : 's'})</span>
          )}
        </span>
        {isRouteFiltered && (
          <button
            onClick={onClearSelection}
            className="ml-2 inline-flex items-center gap-1 text-[10px] text-primary hover:underline"
            title="Esc"
          >
            <XIcon className="h-3 w-3" />Show all routes
          </button>
        )}
        {algoOrderCount > 0 && (
          <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full bg-primary/10 text-primary">
            <Play className="h-3 w-3" />
            {algoOrderCount} algo
          </span>
        )}
        <button
          onClick={() => setShowSubOrderPanel(v => !v)}
          className={`inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors ${algoOrderCount > 0 ? 'ml-2' : 'ml-auto'}`}
          title="Pending sub-orders"
        >
          <ChevronDown className={`h-3 w-3 transition-transform ${showSubOrderPanel ? '' : '-rotate-90'}`} />
          Sub-Orders
          {pendingProposalCount > 0 && (
            <span className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-amber-500 text-white text-[10px] font-semibold">
              {pendingProposalCount > 99 ? '99+' : pendingProposalCount}
            </span>
          )}
        </button>
        <button
          onClick={() => setCheatsheetOpen(true)}
          className={`inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground ${algoOrderCount > 0 ? 'ml-2' : 'ml-auto'}`}
          title="Show keyboard shortcuts (?)"
        >
          <Keyboard className="h-3 w-3" />Shortcuts (?)
        </button>
      </div>

      {/* ── Order Pane (top — fixed 55%) ───────────────────────────────── */}
      <section
        aria-label="Orders"
        className={`flex flex-col min-h-[200px] basis-[55%] shrink-0 space-y-2 rounded-md transition-colors overflow-hidden ${activePane === 'orders' ? 'ring-1 ring-primary/40' : ''}`}
        onMouseDown={() => setActivePane('orders')}
        tabIndex={-1}
      >
        <div className="flex-1 min-h-0 overflow-hidden">
          <OrderTable
            orders={orders}
            allOrders={allOrders}
            selectedOrders={selectedOrders}
            onSelectionChange={onSelectionChange}
            isLoading={isLoading}
            filters={filters}
            onFilterChange={onFilterChange}
            onModifyOrder={onModifyOrder}
            routes={routes}
            onRouteCompleted={onRefresh}
            currentTrader={currentTrader}
          />
        </div>
        <BatchOperationPanel
          selectedOrderIds={Array.from(selectedOrders)}
          selectedOrders={orders.filter(o => selectedOrders.has(o.id))}
          onBatchUpdate={onBatchUpdate}
          onClearSelection={onClearSelection}
          isLoading={isLoading}
        />
      </section>

      {/* ── Route Pane (bottom — fixed 45%) ───────────────────────────── */}
      <section
        aria-label="Routes"
        className={`flex flex-col min-h-[160px] basis-[45%] shrink-0 space-y-2 rounded-md transition-colors overflow-hidden ${activePane === 'routes' ? 'ring-1 ring-primary/40' : ''}`}
        onMouseDown={() => setActivePane('routes')}
        tabIndex={-1}
      >
        <div className="flex-1 min-h-0 overflow-hidden">
          <RouteTable
            routes={displayedRoutes}
            isLoading={isLoading}
            currentTrader={currentTrader}
            onCancelRoute={onCancelRoute}
            onModifyRoute={onModifyRoute}
            onRefresh={onRefresh}
          />
        </div>
      </section>

      {/* ── Sub-Order Review Panel (collapsible) ──────────────────── */}
      {showSubOrderPanel && (
        <section className="flex flex-col min-h-[80px] max-h-[35%] shrink-0 rounded-md border p-3 overflow-y-auto bg-muted/10">
          <SubOrderReviewPanel
            currentTrader={currentTrader}
            onRefresh={onRefresh}
          />
        </section>
      )}

      {/* Algo Launch Dialog */}
      <AlgoLaunchDialog
        order={algoLaunchOrder}
        open={isAlgoDialogOpen}
        onOpenChange={setIsAlgoDialogOpen}
        onConfirm={handleAlgoConfirm}
      />
    </div>
  );
}