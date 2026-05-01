/**
 * BatchRouteOrderDialog — multi-broker batch routing.
 *
 * UX model (re-designed 2026-04-28):
 *   1. User picks N brokers from a checklist at the top of the dialog. Each
 *      parent order automatically gets one destination per selected broker.
 *   2. For each selected broker the user picks a strategy (default: VWAP
 *      when available, else the broker's first strategy) and edits its
 *      strategy parameters once — the same params apply to every destination
 *      using that broker.
 *   3. Per-order quantities are equally split across the chosen brokers,
 *      lot-rounded down. The user can override per-destination qty inline;
 *      the row turns red if any qty is an odd lot or the per-order total
 *      exceeds the parent's remaining quantity.
 *   4. Order type and price are inherited per parent (no batch override) so
 *      a LIMIT order routes as LIMIT with the parent's price.
 *
 * Backend contract: POST /api/orders/batch-route
 *   - dryRun=true returns ApiResponse<BatchOperationResult> for validation
 *   - dryRun=false streams NDJSON: one line per item, then {"summary": ...}
 *   - clientKey = "${orderId}#${broker}" disambiguates split destinations.
 *
 * Compliance (server-enforced, hard block):
 *   USD notional < 10K, USD notional > 49M, JP odd lot.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  GitBranch,
  AlertTriangle,
  Loader2,
  CheckCircle2,
  Scale,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { apiService } from '@/services/api';
import { useBrokerAlgorithms } from '@/hooks/use-broker-algorithms';
import {
  useMarketBrokerMapping,
  applyMappingFilter,
  deriveMarketKey,
} from '@/hooks/use-market-broker-mapping';
import {
  BrokerStrategyFields,
  useStrategyFields,
} from '@/components/broker-strategy-fields';
import { ViolationList, violationLabel } from '@/components/compliance-violation';
import type {
  Order,
  Route,
  TimeInForce,
  BatchRouteOrderRequest,
  BatchRouteOrderItem,
  BatchOperationItemResult,
  BatchOperationResult,
  Violation,
} from '@/types';

const tifOptions: { value: TimeInForce; label: string }[] = [
  { value: 'DAY', label: 'Day' },
  { value: 'GTC', label: 'GTC' },
  { value: 'IOC', label: 'IOC' },
  { value: 'FOK', label: 'FOK' },
];

const QUICK_PCT_PRESETS = [25, 50, 75, 100] as const;

type Phase = 'configure' | 'review' | 'submitting' | 'result';
type AllocStatus = 'BLOCKED' | 'SUCCESS' | 'FAILED';

interface AllocState {
  qty: string;            // user-editable; '' or '0' means skip this destination
  violations: Violation[];
  status?: AllocStatus;
  message?: string;
  routeId?: number | null;
}

interface RowState {
  selected: boolean;
  /** Keyed by broker code. Auto-managed by selectedBrokers reconciliation. */
  allocations: Record<string, AllocState>;
}

interface BatchRouteOrderDialogProps {
  orders: Order[];
  /** All known routes — used to subtract pending WORKING quantity from each
   *  parent order's nominal remainingQuantity so users cannot double-route
   *  what is already out at the broker. */
  routes?: Route[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete?: () => void;
}

/** Route statuses that still consume parent order capacity (i.e. quantity
 *  is at the broker, not yet filled or cancelled). */
const PENDING_ROUTE_STATUSES = new Set([
  'SENT', 'WORKING', 'PARTFILLED', 'QUEUED', 'HOLD',
  'CXLREQ', 'CXLREJ', 'CXLREP', 'CXLRPRQ', 'CXLRPRJ',
  'REPPEN', 'A-SENT', 'OA-SENT',
]);

/** Lot size for an order (PX_ROUND_LOT_SIZE refdata; fallback 100 for JP, else 1). */
function lotSizeOf(o: Order): number {
  if (o.roundLotSize && o.roundLotSize > 0) return o.roundLotSize;
  return (o.exchange ?? '').toUpperCase() === 'JP' ? 100 : 1;
}

function floorToLot(qty: number, lot: number): number {
  if (!Number.isFinite(qty) || qty <= 0 || lot <= 0) return 0;
  return Math.floor(qty / lot) * lot;
}

/** Equally split `remaining` across `n` destinations, lot-floored.
 *  Last bucket absorbs the residual lots so ∑ == floorToLot(remaining, lot). */
function equalSplit(remaining: number, lot: number, n: number): number[] {
  if (n <= 0) return [];
  const totalLots = Math.floor(remaining / lot);
  if (totalLots <= 0) return Array(n).fill(0);
  const baseLots = Math.floor(totalLots / n);
  const extra = totalLots - baseLots * n;
  return Array.from({ length: n }, (_, i) =>
    (baseLots + (i < extra ? 1 : 0)) * lot,
  );
}

/** Pick a sensible default strategy for a broker — prefer VWAP, else first.
 *  Match logic: normalize to alphanumerics, then prefer exact `VWAP`,
 *  then any name starting with `VWAP` that is not a TWAP variant
 *  (covers broker-specific aliases like `VWAP.`, `VWAP_LIQ`, `VWAP1`). */
function defaultStrategyFor(strategies: string[]): string {
  if (strategies.length === 0) return '';
  const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const exact = strategies.find(s => norm(s) === 'VWAP');
  if (exact) return exact;
  const variant = strategies.find(s => {
    const n = norm(s);
    return n.startsWith('VWAP') && !n.includes('TWAP');
  });
  return variant ?? strategies[0];
}

function clientKeyOf(orderId: string, broker: string): string {
  return `${orderId}#${broker}`;
}

export function BatchRouteOrderDialog({
  orders,
  routes,
  open,
  onOpenChange,
  onComplete,
}: BatchRouteOrderDialogProps) {
  // ── Broker selection (top section) ──────────────────────────────────────
  const [selectedBrokers, setSelectedBrokers] = useState<string[]>([]);
  const [brokerStrategies, setBrokerStrategies] = useState<Record<string, string>>({});
  const [tif, setTif] = useState<TimeInForce>('DAY');
  const [notes, setNotes] = useState('');

  // ── Per-order state ─────────────────────────────────────────────────────
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [phase, setPhase] = useState<Phase>('configure');
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const [summary, setSummary] = useState<BatchOperationResult | null>(null);
  // Quick-fill toolbar custom % input (free form). Defaults to 100.
  const [customPct, setCustomPct] = useState('100');

  // Per-broker strategy-params builders, keyed by broker.
  // Registered by BrokerStrategyParamsEditor on mount; deregistered on unmount.
  type ParamsBuilder = () => ReturnType<
    ReturnType<typeof useStrategyFields>['toStrategyParams']
  >;
  const paramsBuildersRef = useRef<Map<string, ParamsBuilder>>(new Map());
  // Snapshot of user-edited strategy params, keyed by `${broker}#${strategy}`.
  // Lets users toggle a broker off and back on without losing the params
  // they just typed.
  type ParamsSnapshot = ReturnType<
    ReturnType<typeof useStrategyFields>['toStrategyParams']
  >;
  const paramsCacheRef = useRef<Map<string, ParamsSnapshot>>(new Map());
  const cacheKey = (broker: string, strategy: string) => `${broker}#${strategy}`;
  const registerParamsBuilder = useCallback(
    (broker: string, builder: ParamsBuilder | null) => {
      if (builder === null) paramsBuildersRef.current.delete(broker);
      else paramsBuildersRef.current.set(broker, builder);
    },
    [],
  );

  // Pending working quantity per parent order (sum of route.working for
  // routes whose status is in PENDING_ROUTE_STATUSES). Capacity already
  // committed at the broker that should NOT be re-allocated.
  const pendingWorkingByOrder = useMemo(() => {
    const map: Record<string, number> = {};
    if (!routes || routes.length === 0) return map;
    for (const r of routes) {
      if (!PENDING_ROUTE_STATUSES.has((r.status ?? '').toUpperCase())) continue;
      const oid = String(r.sequence);
      const w = Number(r.working ?? 0);
      if (!Number.isFinite(w) || w <= 0) continue;
      map[oid] = (map[oid] ?? 0) + w;
    }
    return map;
  }, [routes]);

  /** What the user is actually allowed to allocate now: order's own remaining
   *  minus quantity already working at the broker. Never negative. */
  const effectiveRemainingOf = useCallback(
    (o: Order): number => {
      const pending = pendingWorkingByOrder[o.id] ?? 0;
      return Math.max(0, o.remainingQuantity - pending);
    },
    [pendingWorkingByOrder],
  );

  // ── Catalog data ────────────────────────────────────────────────────────
  const { configs } = useBrokerAlgorithms();
  const { allowedFor: allowedBrokersFor } = useMarketBrokerMapping();

  const allBrokers = useMemo(
    () => configs.map(c => c.broker).filter((b, i, a) => a.indexOf(b) === i).sort(),
    [configs],
  );
  const strategiesFor = useCallback(
    (b: string): string[] => {
      if (!b) return [];
      return configs
        .filter(c => c.broker === b)
        .flatMap(c => c.strategies?.map(s => s.name) ?? [])
        .filter((s, i, a) => a.indexOf(s) === i)
        .sort();
    },
    [configs],
  );

  /** Brokers visible at the top: only those allowed by Market Broker Mapping
   *  for at least one selected order's market (or for the union of all
   *  parent orders' markets when none are selected yet). Falls back to the
   *  full list when the mapping has nothing to say about any market. */
  const visibleBrokers = useMemo(() => {
    if (allBrokers.length === 0) return [];
    const markets = Array.from(new Set(
      orders.map(o => deriveMarketKey(o.exchange, o.currency)).filter(Boolean) as string[],
    ));
    if (markets.length === 0) return allBrokers;
    // Union of allowed brokers across all parent markets. If any market has
    // no row configured we fall back to the full list (consistent with
    // applyMappingFilter's null handling).
    const unionAllowed = new Set<string>();
    let anyUnconfigured = false;
    for (const m of markets) {
      const allowed = allowedBrokersFor(m);
      if (allowed === null) { anyUnconfigured = true; break; }
      for (const b of allowed) unionAllowed.add(b);
    }
    if (anyUnconfigured) return allBrokers;
    const filtered = allBrokers.filter(b => unionAllowed.has(b));
    return filtered.length > 0 ? filtered : allBrokers;
  }, [allBrokers, allowedBrokersFor, orders]);

  /** Brokers allowed for a specific order's market (used to grey-out a
   *  column when the broker is not allowed for that order's market). */
  const isBrokerAllowedFor = useCallback(
    (broker: string, o: Order): boolean => {
      const market = deriveMarketKey(o.exchange, o.currency);
      const filtered = applyMappingFilter([broker], allowedBrokersFor(market));
      return filtered.includes(broker);
    },
    [allowedBrokersFor],
  );

  // ── Reset on dialog open ────────────────────────────────────────────────
  const prevOpenRef = useRef(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      setSelectedBrokers([]);
      setBrokerStrategies({});
      setTif('DAY');
      setNotes('');
      setError('');
      setPhase('configure');
      setProgress(0);
      setSummary(null);
      setCustomPct('100');
      paramsBuildersRef.current.clear();
      paramsCacheRef.current.clear();
      const init: Record<string, RowState> = {};
      for (const o of orders) {
        init[o.id] = { selected: true, allocations: {} };
      }
      setRows(init);
    }
    prevOpenRef.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ── Reconcile rows when parent order list refreshes (poll/WS tick) ──────
  useEffect(() => {
    if (!open) return;
    setRows(prev => {
      let changed = false;
      const next: Record<string, RowState> = {};
      const seen = new Set<string>();
      for (const o of orders) {
        seen.add(o.id);
        if (prev[o.id]) {
          next[o.id] = prev[o.id];
        } else {
          next[o.id] = { selected: false, allocations: {} };
          changed = true;
        }
      }
      for (const oid of Object.keys(prev)) {
        if (!seen.has(oid)) changed = true;
      }
      return changed ? next : prev;
    });
  }, [open, orders]);

  // ── Reconcile allocations when selectedBrokers changes ──────────────────
  // For each row: add allocations for new brokers (qty = equal split based
  // on remaining / N), drop allocations for removed brokers (preserves any
  // user edits on still-present brokers).
  useEffect(() => {
    if (!open) return;
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const lot = lotSizeOf(o);
        const splits = equalSplit(effectiveRemainingOf(o), lot, selectedBrokers.length);
        const allocs: Record<string, AllocState> = {};
        selectedBrokers.forEach((b, i) => {
          const existing = r.allocations[b];
          // Preserve user edits if a non-default qty was entered. We treat
          // the equal-split value as "default" — if the existing qty equals
          // the prior equal-split for that broker (or is empty), we replace
          // with the fresh split; otherwise we keep the user's value.
          const fresh = String(splits[i] ?? 0);
          allocs[b] = existing
            ? existing
            : { qty: fresh, violations: [] };
        });
        next[oid] = { selected: r.selected, allocations: allocs };
      }
      // Snapshot + clean up params for brokers no longer selected.
      // The builder closure still captures live useStrategyFields state at
      // the moment we call it (before the editor unmounts), so cached
      // params include the user's edits.
      for (const b of Array.from(paramsBuildersRef.current.keys())) {
        if (selectedBrokers.includes(b)) continue;
        const builder = paramsBuildersRef.current.get(b);
        const strat = brokerStrategies[b] || '';
        if (builder && strat) {
          try {
            const snap = builder();
            if (snap) paramsCacheRef.current.set(cacheKey(b, strat), snap);
          } catch { /* swallow — keep cache stable on error */ }
        }
        paramsBuildersRef.current.delete(b);
      }
      return next;
    });
    // Note: we re-run when selectedBrokers changes; we do NOT depend on
    // `rows` here (would loop) or `orders` (handled by previous effect).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBrokers, open]);

  // ── Selectors ───────────────────────────────────────────────────────────
  const selectedOrders = useMemo(
    () => orders.filter(o => rows[o.id]?.selected),
    [orders, rows],
  );

  const computeAllocQty = (a: AllocState | undefined): number => {
    if (!a || a.qty === '') return 0;
    const q = parseInt(a.qty, 10);
    return Number.isFinite(q) && q > 0 ? q : 0;
  };

  const rowTotalQty = (r: RowState): number =>
    Object.values(r.allocations).reduce((acc, a) => acc + computeAllocQty(a), 0);

  const totalDestinations = useMemo(() => {
    let c = 0;
    for (const o of selectedOrders) {
      const r = rows[o.id];
      if (!r) continue;
      for (const b of selectedBrokers) {
        if (computeAllocQty(r.allocations[b]) > 0) c += 1;
      }
    }
    return c;
  }, [selectedOrders, rows, selectedBrokers]);

  // ── Mutations ───────────────────────────────────────────────────────────
  const toggleBroker = (b: string) => {
    setSelectedBrokers(prev => {
      if (prev.includes(b)) return prev.filter(x => x !== b);
      return [...prev, b];
    });
    setBrokerStrategies(prev => {
      if (b in prev) return prev;
      const def = defaultStrategyFor(strategiesFor(b));
      return { ...prev, [b]: def };
    });
  };

  const setBrokerStrategy = (b: string, s: string) => {
    setBrokerStrategies(prev => ({ ...prev, [b]: s }));
    // The new strategy has different params; drop the stale builder so the
    // next mounted editor for this broker re-registers.
    paramsBuildersRef.current.delete(b);
  };

  const patchRow = (oid: string, patch: Partial<RowState>) =>
    setRows(prev => ({ ...prev, [oid]: { ...prev[oid], ...patch } }));

  const patchAlloc = (oid: string, broker: string, patch: Partial<AllocState>) =>
    setRows(prev => {
      const r = prev[oid];
      if (!r) return prev;
      const cur = r.allocations[broker];
      if (!cur) return prev;
      return {
        ...prev,
        [oid]: {
          ...r,
          allocations: { ...r.allocations, [broker]: { ...cur, ...patch } },
        },
      };
    });

  /** Re-equal-split the remaining quantity across all selected brokers for
   *  every selected row. Wipes user qty edits — that's the explicit intent. */
  const equalSplitAllSelected = () => {
    if (selectedBrokers.length === 0) {
      setError('Pick at least one broker first.');
      return;
    }
    setError('');
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        if (!r.selected) { next[oid] = r; continue; }
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const lot = lotSizeOf(o);
        const splits = equalSplit(effectiveRemainingOf(o), lot, selectedBrokers.length);
        const allocs: Record<string, AllocState> = { ...r.allocations };
        selectedBrokers.forEach((b, i) => {
          const cur = allocs[b];
          allocs[b] = {
            qty: String(splits[i] ?? 0),
            violations: cur?.violations ?? [],
            status: cur?.status,
            message: cur?.message,
            routeId: cur?.routeId,
          };
        });
        next[oid] = { ...r, allocations: allocs };
      }
      return next;
    });
  };

  /** % Quick-fill: each selected order's *total* qty becomes pct% of remaining
   *  (lot-floored at the order level), then equally split across the chosen
   *  brokers (lot-floored). Multi-broker rows fully participate — unlike the
   *  old single-destination-only quick-fill, this one rebalances everything. */
  const applyPercentQty = (pct: number) => {
    if (selectedBrokers.length === 0) {
      setError('Pick at least one broker first.');
      return;
    }
    if (!Number.isFinite(pct) || pct <= 0 || pct > 100) {
      setError('Please enter a percentage between 1 and 100.');
      return;
    }
    setError('');
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        if (!r.selected) { next[oid] = r; continue; }
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const lot = lotSizeOf(o);
        // Apply pct to effective remaining (post-working), then floor to lot.
        const target = floorToLot((effectiveRemainingOf(o) * pct) / 100, lot);
        const splits = equalSplit(target, lot, selectedBrokers.length);
        const allocs: Record<string, AllocState> = { ...r.allocations };
        selectedBrokers.forEach((b, i) => {
          const cur = allocs[b];
          allocs[b] = {
            qty: String(splits[i] ?? 0),
            violations: cur?.violations ?? [],
            status: cur?.status,
            message: cur?.message,
            routeId: cur?.routeId,
          };
        });
        next[oid] = { ...r, allocations: allocs };
      }
      return next;
    });
  };

  /** Per-broker column quick-fill: set THIS broker's qty to pct% of each
   *  selected order's effective remaining (lot-floored). Other brokers'
   *  cells are untouched \u2014 row total may exceed remain (cell turns red),
   *  which is fine: user explicitly asked for "broker A gets 50%". */
  const applyPercentToBroker = (broker: string, pct: number) => {
    if (!selectedBrokers.includes(broker)) {
      setError(`Pick broker ${broker} first.`);
      return;
    }
    if (!Number.isFinite(pct) || pct <= 0 || pct > 100) {
      setError('Please pick a percentage between 1 and 100.');
      return;
    }
    setError('');
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        if (!r.selected) { next[oid] = r; continue; }
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const lot = lotSizeOf(o);
        const target = floorToLot((effectiveRemainingOf(o) * pct) / 100, lot);
        const cur = r.allocations[broker];
        next[oid] = {
          ...r,
          allocations: {
            ...r.allocations,
            [broker]: {
              qty: String(target),
              violations: cur?.violations ?? [],
              status: cur?.status,
              message: cur?.message,
              routeId: cur?.routeId,
            },
          },
        };
      }
      return next;
    });
  };

  // ── Build the API request payload ───────────────────────────────────────
  const buildRequest = (dryRun: boolean): BatchRouteOrderRequest => {
    // Template carries shared TIF + notes only. Everything broker- and
    // order-specific is set per-item.
    const template: BatchRouteOrderRequest['template'] = {
      timeInForce: tif,
      notes: notes || undefined,
    };

    const items: BatchRouteOrderItem[] = [];
    for (const o of selectedOrders) {
      const r = rows[o.id];
      if (!r) continue;
      for (const b of selectedBrokers) {
        const alloc = r.allocations[b];
        const qty = computeAllocQty(alloc);
        if (qty <= 0) continue;
        // On real submission, skip destinations the dry-run flagged BLOCKED.
        // Forces user to either fix qty and re-Validate or accept that this
        // destination will be omitted; avoids re-submitting a known reject.
        if (!dryRun && alloc?.status === 'BLOCKED') continue;
        const strat = brokerStrategies[b] || '';
        const override: Partial<BatchRouteOrderRequest['template']> & {
          quantity?: number;
        } = {
          broker: b,
          quantity: qty,
          orderType: o.orderType, // inherit per parent
        };
        if (strat) override.strategy = strat;
        // Inherit limit price from parent order for LIMIT/STOP_LIMIT.
        if ((o.orderType === 'LIMIT' || o.orderType === 'STOP_LIMIT')
            && o.price != null) {
          override.price = o.price;
        }
        if ((o.orderType === 'STOP' || o.orderType === 'STOP_LIMIT')
            && o.stopPrice != null) {
          override.stopPrice = o.stopPrice;
        }
        if (strat) {
          const buildParams = paramsBuildersRef.current.get(b);
          if (buildParams) {
            const sp = buildParams();
            if (sp) override.strategyParams = sp;
          }
        }
        items.push({
          orderId: o.id,
          clientKey: clientKeyOf(o.id, b),
          override,
        });
      }
    }

    return { template, items, dryRun };
  };

  // ── Validation gate before review ───────────────────────────────────────
  const canValidate = useMemo(() => {
    if (selectedOrders.length === 0) return false;
    if (selectedBrokers.length === 0) return false;
    for (const o of selectedOrders) {
      const r = rows[o.id];
      if (!r) return false;
      const lot = lotSizeOf(o);
      let total = 0;
      let anyPositive = false;
      for (const b of selectedBrokers) {
        const q = computeAllocQty(r.allocations[b]);
        if (q <= 0) continue;
        // Odd-lot guard: must be a multiple of round-lot.
        if (lot > 1 && q % lot !== 0) return false;
        anyPositive = true;
        total += q;
      }
      if (!anyPositive) return false;
      if (total > effectiveRemainingOf(o)) return false;
    }
    return true;
  }, [selectedOrders, selectedBrokers, rows, effectiveRemainingOf]);

  // ── Blocked-destination details for inline banner ──────────────────────
  // Derived from rows after dry-run / submit fills in violations + status.
  // Each entry: { orderId, symbol, broker, violations[] }.
  const blockedDetails = useMemo(() => {
    const out: { orderId: string; symbol: string; broker: string; violations: Violation[] }[] = [];
    const orderById: Record<string, Order> = {};
    for (const o of orders) orderById[o.id] = o;
    for (const [oid, row] of Object.entries(rows)) {
      const o = orderById[oid];
      if (!o) continue;
      for (const [broker, alloc] of Object.entries(row.allocations)) {
        if (alloc.status !== 'BLOCKED') continue;
        out.push({
          orderId: oid,
          symbol: o.symbol,
          broker,
          violations: alloc.violations ?? [],
        });
      }
    }
    return out;
  }, [orders, rows]);

  // ── FAILED-destination details (live submit only) ──────────────────────
  // Distinct from blockedDetails: FAILED == EMSX backend rejection (e.g.
  // "Invalid Handling Instruction" when broker code is not enabled for EMSX
  // API staging — broker-side configuration issue, not a pre-trade rule).
  const failedDetails = useMemo(() => {
    const out: { orderId: string; symbol: string; broker: string; message: string }[] = [];
    const orderById: Record<string, Order> = {};
    for (const o of orders) orderById[o.id] = o;
    for (const [oid, row] of Object.entries(rows)) {
      const o = orderById[oid];
      if (!o) continue;
      for (const [broker, alloc] of Object.entries(row.allocations)) {
        if (alloc.status !== 'FAILED') continue;
        out.push({
          orderId: oid,
          symbol: o.symbol,
          broker,
          message: alloc.message ?? '(no error detail returned)',
        });
      }
    }
    return out;
  }, [orders, rows]);

  // ── Apply BatchOperationItemResult[] back onto allocation state ─────────
  const applyResults = (results: BatchOperationItemResult[]) => {
    setRows(prev => {
      const next: Record<string, RowState> = { ...prev };
      for (const item of results) {
        const hashIdx = item.key.indexOf('#');
        if (hashIdx < 0) continue;
        const oid = item.key.slice(0, hashIdx);
        const broker = item.key.slice(hashIdx + 1);
        const r = next[oid];
        if (!r) continue;
        const cur = r.allocations[broker];
        if (!cur) continue;
        next[oid] = {
          ...r,
          allocations: {
            ...r.allocations,
            [broker]: {
              ...cur,
              status: item.status,
              message: item.message,
              violations: item.violations,
              routeId: item.routeId ?? null,
            },
          },
        };
      }
      return next;
    });
  };

  // ── Run dry-run validation, transition to Review ────────────────────────
  const runValidation = async () => {
    setError('');
    setPhase('submitting');
    const req = buildRequest(true);
    const res = await apiService.dryRunBatchRoute(req);
    if (!res.success || !res.data) {
      setError(res.error || 'Validation failed');
      setPhase('configure');
      return;
    }
    applyResults(res.data.items);
    // Don't auto-deselect blocked rows — the user may want to fix the qty
    // and re-validate. The Submit step only sends destinations whose qty is
    // > 0; blocked-but-still-selected rows surface in the banner so the
    // user can either zero them out or unblock them by editing.
    setSummary(res.data);
    setPhase('review');
    if (res.data.blocked > 0) {
      setError('Some destinations failed pre-trade checks. See the banner for which broker on which order; edit qty and Validate again, or proceed to Submit (blocked items will be skipped).');
    }
  };

  // ── Submit (after review) — NDJSON streaming ────────────────────────────
  const runSubmit = async () => {
    setError('');
    setPhase('submitting');
    setProgress(0);
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        const allocs: Record<string, AllocState> = {};
        for (const [b, a] of Object.entries(r.allocations)) {
          allocs[b] = { ...a, status: undefined, message: undefined, routeId: undefined };
        }
        next[oid] = { ...r, allocations: allocs };
      }
      return next;
    });
    const req = buildRequest(false);
    let count = 0;
    const res = await apiService.streamBatchRoute(
      req,
      (item: BatchOperationItemResult) => {
        count += 1;
        setProgress(count);
        applyResults([item]);
      },
      (s: BatchOperationResult) => setSummary(s),
    );
    if (!res.success) setError(res.error || 'Submission failed');
    setPhase('result');
  };

  const close = () => {
    if (phase === 'submitting') return;
    if (phase === 'result') onComplete?.();
    onOpenChange(false);
  };

  const editable = phase === 'configure' || phase === 'review';

  // ────────────────────────────────────────────────────────────────────────
  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) close(); }}>
      <DialogContent className="sm:max-w-6xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            {orders.length === 1
              ? `Route Order — ${orders[0]?.symbol ?? orders[0]?.id}`
              : `Batch Route — ${orders.length} orders`}
          </DialogTitle>
          <DialogDescription>
            Pick brokers, set each broker's algo + params, then review qty
            splits per order. Order type and price are inherited from each
            parent order. Each order's available capacity = remaining
            quantity \u2212 quantity already working at the broker.
            Compliance (USD &lt; 10K / &gt; 49M, JP odd lot) is enforced
            server-side.
          </DialogDescription>
        </DialogHeader>

        {/* ── Broker selection ──────────────────────────────────────────── */}
        <div className="border border-border rounded p-3 bg-secondary/20 space-y-2">
          <div className="flex items-center gap-2">
            <Label className="text-xs">Brokers</Label>
            <span className="text-[11px] text-muted-foreground">
              {selectedBrokers.length === 0
                ? 'Pick one or more brokers — each becomes its own destination per order.'
                : `${selectedBrokers.length} broker${selectedBrokers.length === 1 ? '' : 's'} selected`}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {visibleBrokers.map(b => {
              const checked = selectedBrokers.includes(b);
              return (
                <label
                  key={b}
                  className={
                    'inline-flex items-center gap-1.5 px-2 py-1 rounded border cursor-pointer text-xs select-none ' +
                    (checked
                      ? 'bg-primary/15 border-primary/60'
                      : 'bg-background border-border hover:bg-accent')
                  }
                >
                  <Checkbox
                    checked={checked}
                    onCheckedChange={() => editable && toggleBroker(b)}
                    disabled={!editable}
                  />
                  <span className="font-mono">{b}</span>
                </label>
              );
            })}
            {visibleBrokers.length === 0 && (
              <span className="text-xs text-muted-foreground">No brokers available.</span>
            )}
          </div>
        </div>

        {/* ── Per-broker strategy + params ──────────────────────────────── */}
        {selectedBrokers.length > 0 && (
          <div className="border border-border rounded p-3 space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-semibold text-muted-foreground">
                Strategy &amp; parameters per broker
              </div>
              <button
                type="button"
                onClick={() => {
                  // Reset every selected broker to its computed default
                  // strategy (VWAP-preferred) and clear cached parameter
                  // edits so the editor re-fetches a fresh field set.
                  setBrokerStrategies(() => {
                    const next: Record<string, string> = {};
                    for (const b of selectedBrokers) next[b] = defaultStrategyFor(strategiesFor(b));
                    return next;
                  });
                  paramsBuildersRef.current.clear();
                  paramsCacheRef.current.clear();
                }}
                className="text-[11px] text-primary hover:underline"
                disabled={!editable}
                title="Reset every selected broker to its default strategy and clear unsaved parameter edits"
              >
                Reset to defaults
              </button>
            </div>
            {selectedBrokers.map(b => (
              <BrokerStrategyParamsEditor
                key={b}
                broker={b}
                strategy={brokerStrategies[b] || ''}
                strategies={strategiesFor(b)}
                onStrategyChange={(s) => setBrokerStrategy(b, s)}
                registerParamsBuilder={registerParamsBuilder}
                getCachedSnapshot={(br, st) => paramsCacheRef.current.get(cacheKey(br, st))}
                disabled={!editable}
              />
            ))}
          </div>
        )}

        {/* ── Shared TIF + notes ────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">TIF (all routes)</Label>
            <Select value={tif} onValueChange={(v) => setTif(v as TimeInForce)} disabled={!editable}>
              <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
              <SelectContent>
                {tifOptions.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="col-span-2">
            <Label className="text-xs">Notes</Label>
            <Input value={notes} onChange={(e) => setNotes(e.target.value)}
              className="h-8" disabled={!editable} />
          </div>
        </div>

        {/* ── Quick-fill / equal-split toolbar ──────────────────────────── */}
        <div className="flex flex-wrap items-center gap-2 px-2 py-1.5 bg-secondary/30 border border-border rounded text-xs">
          <span className="text-muted-foreground">Quick-fill qty:</span>
          {QUICK_PCT_PRESETS.map(pct => (
            <Button
              key={pct}
              variant="outline"
              size="sm"
              className="h-6 px-2 text-xs"
              onClick={() => applyPercentQty(pct)}
              disabled={!editable || selectedBrokers.length === 0 || selectedOrders.length === 0}
              title={`Set each selected order's total qty to ${pct}% of its remaining, then split equally across the chosen brokers (lot-rounded).`}
            >
              {pct}%
            </Button>
          ))}
          <Input
            type="number"
            min={1}
            max={100}
            step={1}
            value={customPct}
            onChange={e => {
              // Clamp at the input layer so users cannot enter 250 or -30
              // and only discover the rejection on Apply.
              const v = e.target.value;
              if (v === '') { setCustomPct(''); return; }
              const n = Number(v);
              if (!Number.isFinite(n)) return;
              setCustomPct(String(Math.max(1, Math.min(100, Math.round(n)))));
            }}
            onWheel={e => e.currentTarget.blur()}
            className="h-6 w-16 text-xs"
            disabled={!editable || selectedBrokers.length === 0 || selectedOrders.length === 0}
            title="Custom percentage (1\u2013100)"
          />
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => applyPercentQty(Number(customPct))}
            disabled={!editable || selectedBrokers.length === 0 || selectedOrders.length === 0}
          >
            Apply %
          </Button>
          <div className="w-px h-4 bg-border mx-1" />
          <Button
            variant="outline"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={equalSplitAllSelected}
            disabled={!editable || selectedBrokers.length === 0 || selectedOrders.length === 0}
            title="Equally divide each selected order's remaining quantity across the chosen brokers (lot-rounded)"
          >
            <Scale className="h-3 w-3 mr-1" />
            Equal-split 100%
          </Button>
          <span className="ml-auto text-muted-foreground/70">
            Each qty cell is editable. Cells turn red on odd-lot or row over-allocation.
          </span>
        </div>

        {/* ── Per-row table ─────────────────────────────────────────────── */}
        <div className="border border-border rounded overflow-hidden">
          <div className="max-h-[50vh] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-secondary/50 sticky top-0 z-10">
                <tr>
                  <th className="w-8 text-center"></th>
                  <th className="text-left px-2 py-1">Order</th>
                  <th className="text-left px-2 py-1">Ticker</th>
                  <th className="text-left px-2 py-1">Side</th>
                  <th className="text-left px-2 py-1">Type</th>
                  <th className="text-right px-2 py-1">Price</th>
                  <th className="text-right px-2 py-1">Remain</th>
                  {selectedBrokers.map(b => (
                    <th key={b} className="text-right px-2 py-1 font-mono">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <button
                            type="button"
                            disabled={!editable}
                            className="inline-flex items-center gap-1 hover:text-primary disabled:opacity-60 disabled:cursor-not-allowed"
                            title={`Quick-fill ${b} column with % of each selected order's effective remaining`}
                          >
                            {b}
                            <span className="text-[9px] text-muted-foreground/70">▾</span>
                          </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="text-xs">
                          {QUICK_PCT_PRESETS.map(pct => (
                            <DropdownMenuItem
                              key={pct}
                              onSelect={() => applyPercentToBroker(b, pct)}
                            >
                              Set {b} = {pct}% of remain
                            </DropdownMenuItem>
                          ))}
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => applyPercentToBroker(b, 0)}
                            disabled
                          >
                            Custom % — use toolbar input
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </th>
                  ))}
                  <th className="text-right px-2 py-1">Σ Qty</th>
                  <th className="text-left px-2 py-1">Status</th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 && (
                  <tr><td colSpan={8 + selectedBrokers.length} className="text-center py-6 text-muted-foreground">
                    No orders.
                  </td></tr>
                )}
                {orders.map(o => {
                  const r = rows[o.id];
                  if (!r) return null;
                  const lot = lotSizeOf(o);
                  const total = rowTotalQty(r);
                  const effRemain = effectiveRemainingOf(o);
                  const pendingWorking = pendingWorkingByOrder[o.id] ?? 0;
                  const overAlloc = total > effRemain;
                  const anyAlloc = Object.values(r.allocations).some(a => computeAllocQty(a) > 0);
                  return (
                    <OrderRow
                      key={o.id}
                      order={o}
                      row={r}
                      lot={lot}
                      total={total}
                      effectiveRemaining={effRemain}
                      pendingWorking={pendingWorking}
                      overAlloc={overAlloc}
                      anyAlloc={anyAlloc}
                      selectedBrokers={selectedBrokers}
                      isBrokerAllowedFor={isBrokerAllowedFor}
                      onPatchRow={(patch) => patchRow(o.id, patch)}
                      onPatchAlloc={(b, patch) => patchAlloc(o.id, b, patch)}
                      editable={editable}
                      phase={phase}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Status / progress ─────────────────────────────────────────── */}
        {phase === 'submitting' && (
          <p className="text-xs text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-3 w-3 animate-spin" />
            {summary
              ? `Submitted ${progress} / ${totalDestinations}`
              : 'Validating…'}
          </p>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>
              <div>{error}</div>
              {blockedDetails.length > 0 && (
                <details className="mt-2 text-xs">
                  <summary className="cursor-pointer select-none">
                    View {blockedDetails.length} blocked destination
                    {blockedDetails.length === 1 ? '' : 's'}
                  </summary>
                  <ul className="mt-1 space-y-1 max-h-48 overflow-y-auto pr-1">
                    {blockedDetails.map(d => (
                      <li
                        key={`${d.orderId}#${d.broker}`}
                        className="border-l-2 border-red-500/60 pl-2"
                      >
                        <div className="font-mono">
                          <span className="font-semibold">{d.symbol}</span>
                          <span className="text-muted-foreground"> · {d.broker}</span>
                        </div>
                        {d.violations.length === 0 ? (
                          <div className="text-muted-foreground italic">
                            (no violation detail returned)
                          </div>
                        ) : (
                          <ul className="ml-2">
                            {d.violations.map((v, i) => (
                              <li key={`${v.code}-${i}`}>
                                <span className="font-semibold">
                                  {violationLabel(v.code)}
                                </span>
                                <span className="text-muted-foreground"> — {v.message}</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </AlertDescription>
          </Alert>
        )}
        {phase === 'result' && summary && (
          <Alert>
            <AlertDescription>
              <div>
                <strong>Done.</strong> Total {summary.total} ·
                <span className="text-emerald-600"> {summary.succeeded} succeeded</span> ·
                <span className="text-red-600"> {summary.blocked} blocked</span> ·
                <span className="text-amber-600"> {summary.failed} failed</span>
              </div>
              {failedDetails.length > 0 && (
                <details className="mt-2 text-xs" open>
                  <summary className="cursor-pointer select-none">
                    View {failedDetails.length} failed destination
                    {failedDetails.length === 1 ? '' : 's'}
                  </summary>
                  <ul className="mt-1 space-y-1 max-h-48 overflow-y-auto pr-1">
                    {failedDetails.map(d => (
                      <li
                        key={`${d.orderId}#${d.broker}`}
                        className="border-l-2 border-amber-500/60 pl-2"
                      >
                        <div className="font-mono">
                          <span className="font-semibold">{d.symbol}</span>
                          <span className="text-muted-foreground"> · {d.broker}</span>
                        </div>
                        <div className="text-muted-foreground">{d.message}</div>
                        {/Invalid Handling Instruction/i.test(d.message) && (
                          <div className="text-amber-700 dark:text-amber-300 mt-0.5">
                            提示：该 broker 代码未在 EMSX API 中启用 staging
                            权限。请联系 Bloomberg / broker 开通 API
                            授权后再路由。
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {failedDetails.length === 0 &&
                blockedDetails.length > 0 &&
                summary.blocked > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    {blockedDetails.length} blocked — see banner above for
                    details.
                  </div>
                )}
            </AlertDescription>
          </Alert>
        )}

        <DialogFooter>
          {phase === 'configure' && (
            <>
              <Button variant="outline" onClick={close}>Cancel</Button>
              <Button onClick={runValidation} disabled={!canValidate}>
                Validate ({totalDestinations} destination{totalDestinations === 1 ? '' : 's'})
              </Button>
            </>
          )}
          {phase === 'review' && (
            <>
              <Button variant="outline" onClick={() => setPhase('configure')}>Back</Button>
              <Button onClick={runSubmit} disabled={selectedOrders.length === 0}>
                Confirm &amp; Route {totalDestinations} destination{totalDestinations === 1 ? '' : 's'}
              </Button>
            </>
          )}
          {phase === 'submitting' && (
            <Button disabled><Loader2 className="mr-2 h-4 w-4 animate-spin" />Working…</Button>
          )}
          {phase === 'result' && <Button onClick={close}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// OrderRow — single parent order row with one editable qty cell per broker.
// ─────────────────────────────────────────────────────────────────────────────

interface OrderRowProps {
  order: Order;
  row: RowState;
  lot: number;
  total: number;
  /** o.remainingQuantity − pending working at the broker. The number actually
   *  available to the user. */
  effectiveRemaining: number;
  /** Pending working qty already at the broker, surfaced inline so the user
   *  can see *why* the available capacity is less than nominal remaining. */
  pendingWorking: number;
  overAlloc: boolean;
  anyAlloc: boolean;
  selectedBrokers: string[];
  isBrokerAllowedFor: (broker: string, o: Order) => boolean;
  onPatchRow: (patch: Partial<RowState>) => void;
  onPatchAlloc: (broker: string, patch: Partial<AllocState>) => void;
  editable: boolean;
  phase: Phase;
}

function OrderRow(p: OrderRowProps) {
  const { order: o, row: r, lot, total, effectiveRemaining, pendingWorking,
    overAlloc, anyAlloc, selectedBrokers, isBrokerAllowedFor,
    onPatchRow, onPatchAlloc, editable, phase } = p;

  const aggregateStatus: AllocStatus | undefined = useMemo(() => {
    const statuses = Object.values(r.allocations).map(a => a.status).filter(Boolean) as AllocStatus[];
    if (statuses.length === 0) return undefined;
    if (statuses.includes('BLOCKED')) return 'BLOCKED';
    if (statuses.includes('FAILED')) return 'FAILED';
    if (statuses.every(s => s === 'SUCCESS')) return 'SUCCESS';
    return undefined;
  }, [r.allocations]);

  const aggregateViolations: Violation[] = useMemo(() => {
    const seen = new Set<string>();
    const out: Violation[] = [];
    for (const a of Object.values(r.allocations)) {
      for (const v of a.violations ?? []) {
        const key = (v as { code?: string; message?: string }).code
          || (v as { message?: string }).message
          || JSON.stringify(v);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(v);
      }
    }
    return out;
  }, [r.allocations]);

  return (
    <tr className="border-t border-border">
      <td className="text-center">
        <Checkbox
          checked={r.selected}
          onCheckedChange={(v) => onPatchRow({ selected: !!v })}
          disabled={phase === 'submitting' || phase === 'result'}
        />
      </td>
      <td className="px-2 py-1 font-mono">{o.id}</td>
      <td className="px-2 py-1">{o.symbol}</td>
      <td className={`px-2 py-1 font-semibold ${o.side === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>{o.side}</td>
      <td className="px-2 py-1 text-[11px] text-muted-foreground">{o.orderType}</td>
      <td className="px-2 py-1 text-right font-mono-numbers">
        {o.price != null ? o.price.toFixed(2) : '—'}
      </td>
      <td className="px-2 py-1 text-right font-mono-numbers">
        {effectiveRemaining.toLocaleString()}
        <div className="text-[10px] text-muted-foreground/70">
          {pendingWorking > 0
            ? `−${pendingWorking.toLocaleString()} working · lot ${lot}`
            : `lot ${lot}`}
        </div>
      </td>
      {selectedBrokers.map(b => {
        const a = r.allocations[b];
        const q = a ? parseInt(a.qty || '0', 10) : 0;
        const allowed = isBrokerAllowedFor(b, o);
        const oddLot = q > 0 && lot > 1 && q % lot !== 0;
        const cellInvalid = oddLot || (overAlloc && q > 0);
        const allocStatus = a?.status;
        return (
          <td key={b} className="px-2 py-1 text-right">
            {allowed ? (
              <Input
                type="number"
                min={0}
                step={lot}
                value={a?.qty ?? '0'}
                onChange={(e) => onPatchAlloc(b, { qty: e.target.value })}
                onWheel={e => e.currentTarget.blur()}
                className={
                  'h-7 w-24 text-right font-mono text-xs ' +
                  // Use ring instead of bg to avoid contrast issues with the
                  // input's text color in either light or dark mode.
                  // Dashed ring during 'review' (dry-run preview) so the
                  // user can tell pre-flight result apart from a real route.
                  (cellInvalid
                    ? 'ring-2 ring-red-500/70 ring-inset'
                    : (allocStatus === 'SUCCESS'
                      ? (phase === 'review'
                        ? 'ring-2 ring-emerald-500/40 ring-inset ring-dashed'
                        : 'ring-2 ring-emerald-500/40 ring-inset')
                      : (allocStatus === 'BLOCKED'
                        ? (phase === 'review'
                          ? 'ring-2 ring-red-500/40 ring-inset ring-dashed'
                          : 'ring-2 ring-red-500/40 ring-inset')
                        : (allocStatus === 'FAILED'
                          ? 'ring-2 ring-amber-500/40 ring-inset'
                          : ''))))
                }
                disabled={!editable}
                placeholder="0"
                title={oddLot ? `Odd lot — must be a multiple of ${lot}` : undefined}
              />
            ) : (
              <span className="text-[10px] text-muted-foreground italic" title="Broker not allowed for this order's market in Settings → Market Broker Mapping">
                n/a
              </span>
            )}
          </td>
        );
      })}
      <td className={'px-2 py-1 text-right font-mono-numbers ' + (overAlloc ? 'text-red-600 font-semibold' : '')}>
        {total.toLocaleString()}{overAlloc ? ' ⚠' : ''}
        {effectiveRemaining > 0 && (
          <div className="text-[10px] text-muted-foreground/70">
            {Math.round((total / effectiveRemaining) * 100)}% of avail
          </div>
        )}
      </td>
      <td className="px-2 py-1">
        {aggregateStatus === 'SUCCESS' && (
          <span className="text-emerald-600 inline-flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />Routed
          </span>
        )}
        {aggregateStatus === 'BLOCKED' && <ViolationList violations={aggregateViolations} />}
        {aggregateStatus === 'FAILED' && <span className="text-amber-600 text-xs">Some failed</span>}
        {!aggregateStatus && overAlloc && (
          <span className="text-red-600 text-[11px]">Over-allocated</span>
        )}
        {!aggregateStatus && !overAlloc && !anyAlloc && selectedBrokers.length > 0 && (
          <span className="text-muted-foreground text-[11px]">No qty allocated</span>
        )}
      </td>
    </tr>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// BrokerStrategyParamsEditor — top-level editor for one broker.
// ─────────────────────────────────────────────────────────────────────────────

interface BrokerStrategyParamsEditorProps {
  broker: string;
  strategy: string;
  strategies: string[];
  onStrategyChange: (s: string) => void;
  registerParamsBuilder: (
    broker: string,
    builder: (() => ReturnType<
      ReturnType<typeof useStrategyFields>['toStrategyParams']
    >) | null,
  ) => void;
  /** Returns a previously-cached params snapshot for {broker, strategy}, if
   *  any \u2014 used to restore user edits after a toggle off/on cycle. */
  getCachedSnapshot: (broker: string, strategy: string) => ReturnType<
    ReturnType<typeof useStrategyFields>['toStrategyParams']
  > | undefined;
  disabled: boolean;
}

function BrokerStrategyParamsEditor({
  broker,
  strategy,
  strategies,
  onStrategyChange,
  registerParamsBuilder,
  getCachedSnapshot,
  disabled,
}: BrokerStrategyParamsEditorProps) {
  const state = useStrategyFields(broker, strategy, 'EQTY');

  // Restore cached params after the catalog finishes loading the defaults.
  // Tracked by `restoredKeyRef` so we restore exactly once per
  // {broker, strategy} pair \u2014 not on every render of `state.fields`.
  const restoredKeyRef = useRef<string>('');
  useEffect(() => {
    const key = `${broker}#${strategy}`;
    if (!strategy || state.isLoading || state.fields.length === 0) return;
    if (restoredKeyRef.current === key) return;
    const snap = getCachedSnapshot(broker, strategy);
    if (snap && snap.fields && snap.fields.length === state.fields.length) {
      state.setFields(prev => prev.map((f, i) => ({
        ...f,
        value: snap.fields[i]?.value ?? f.value,
        disabled: snap.fields[i]?.disabled ?? f.disabled,
      })));
    }
    restoredKeyRef.current = key;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [broker, strategy, state.isLoading, state.fields.length]);

  // Register a stable builder for this broker so the dialog can collect
  // strategy params at request-build time.
  useEffect(() => {
    registerParamsBuilder(broker, () => state.toStrategyParams(strategy));
    return () => registerParamsBuilder(broker, null);
    // We intentionally re-register whenever the field state or strategy
    // changes so the latest values are captured.
  }, [broker, strategy, state, registerParamsBuilder]);

  return (
    <div className="grid grid-cols-12 gap-3 items-start">
      <div className="col-span-3">
        <Label className="text-xs font-mono">{broker}</Label>
      </div>
      <div className="col-span-3">
        <Select
          value={strategy || '__none__'}
          onValueChange={(v) => onStrategyChange(v === '__none__' ? '' : v)}
          disabled={disabled}
        >
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Strategy..." /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">(none / DMA)</SelectItem>
            {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-6">
        {strategy ? (
          <BrokerStrategyFields
            fields={state.fields}
            setFields={state.setFields}
            isLoading={state.isLoading}
            title=""
            hideWhenEmpty
          />
        ) : (
          <div className="text-[11px] text-muted-foreground italic">No strategy selected — routes will be sent without strategy params.</div>
        )}
      </div>
    </div>
  );
}
