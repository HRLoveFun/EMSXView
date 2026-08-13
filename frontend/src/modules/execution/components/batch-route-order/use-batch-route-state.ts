/**
 * useBatchRouteState — central state hook for BatchRouteOrderDialog.
 *
 * Encapsulates ~600 lines of state, derived computations, and action functions
 * so the dialog component stays a thin <300-line UI orchestrator.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  Order,
  TimeInForce,
  BatchRouteOrderRequest,
  BatchRouteOrderItem,
  BatchOperationItemResult,
  BatchOperationResult,
  Violation,
  Route,
} from '@execution/types';
import { apiService } from '@execution/services/execution-api';
import { useBrokerAlgorithms } from '@execution/hooks/use-broker-algorithms';
import {
  useMarketBrokerMapping,
  applyMappingFilter,
  deriveMarketKey,
} from '@execution/hooks/use-market-broker-mapping';
import { useStrategyFields } from '@execution/components/broker-strategy-fields';
import { getVolumeCapField, VOLUME_CAP_MULTIPLIER } from '@execution/data/broker-volume-cap-mapping';
import { getStartTimeField, getEndTimeField, isValidTimeFormat } from '@execution/data/broker-time-mapping';
import { hhmmToEmsxInt } from '@execution/data/broker-common-params';

import {
  PENDING_ROUTE_STATUSES,
  type Phase,
  type AllocState,
  type RowState,
} from './types';
import {
  lotSizeOf,
  floorToLot,
  equalSplit,
  defaultStrategyFor,
  clientKeyOf,
} from './utils';

// ── Internal types ──────────────────────────────────────────────────────────

type ParamsBuilder = () => ReturnType<
  ReturnType<typeof useStrategyFields>['toStrategyParams']
>;
type ParamsSnapshot = ReturnType<ParamsBuilder>;
type FieldSetter = (fieldName: string, value: string) => void;

export interface UseBatchRouteStateInput {
  orders: Order[];
  routes?: Route[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete?: () => void;
}

export interface UseBatchRouteStateReturn {
  // ── Raw state ──────────────────────────────────────────────────────
  selectedBrokers: string[];
  brokerStrategies: Record<string, string>;
  tif: TimeInForce;
  notes: string;
  rows: Record<string, RowState>;
  phase: Phase;
  error: string;
  progress: number;
  summary: BatchOperationResult | null;
  customPct: string;
  startTime: string;
  endTime: string;
  releaseTime: string;
  ratios: Record<string, number>;

  // ── State setters (for UI fields) ─────────────────────────────────
  setTif: (v: TimeInForce) => void;
  setNotes: (v: string) => void;
  setCustomPct: (v: string) => void;
  setStartTime: (v: string) => void;
  setEndTime: (v: string) => void;
  setReleaseTime: (v: string) => void;
  setPhase: (v: Phase) => void;

  // ── Ratio helpers ─────────────────────────────────────────────────
  ratioSum: number;
  ratioTotalValid: boolean;
  setRatioForBroker: (broker: string, value: number) => void;
  resetRatios: () => void;

  // ── Derived / computed ────────────────────────────────────────────
  routedAmountByOrder: Record<string, number>;
  effectiveRemainingOf: (o: Order) => number;
  allBrokers: string[];
  visibleBrokers: string[];
  strategiesFor: (b: string) => string[];
  isBrokerAllowedFor: (broker: string, o: Order) => boolean;
  selectedOrders: Order[];
  orderMarkets: string[];
  totalDestinations: number;
  canValidate: boolean;
  blockedDetails: { orderId: string; symbol: string; broker: string; violations: Violation[] }[];
  failedDetails: { orderId: string; symbol: string; broker: string; message: string }[];
  warnDetails: { orderId: string; symbol: string; broker: string; violations: Violation[] }[];

  // ── Computed helpers ──────────────────────────────────────────────
  computeAllocQty: (a: AllocState | undefined) => number;
  rowTotalQty: (r: RowState) => number;

  // ── Mutations ─────────────────────────────────────────────────────
  toggleBroker: (b: string) => void;
  setBrokerStrategy: (b: string, s: string) => void;
  patchRow: (oid: string, patch: Partial<RowState>) => void;
  patchAlloc: (oid: string, broker: string, patch: Partial<AllocState>) => void;

  // ── Quick-fill / ratio actions ────────────────────────────────────
  applyPercentQty: (pct: number) => void;
  applyPercentToBroker: (broker: string, pct: number) => void;
  applyTimeToAll: () => void;
  applyRatios: () => void;

  // ── Workflow actions ──────────────────────────────────────────────
  buildRequest: (dryRun: boolean) => BatchRouteOrderRequest;
  runValidation: () => Promise<void>;
  runSubmit: () => Promise<void>;
  close: () => void;

  // ── Misc ──────────────────────────────────────────────────────────
  editable: boolean;
  registerParamsBuilder: (broker: string, builder: ParamsBuilder | null) => void;
  registerFieldSetter: (broker: string, setter: FieldSetter | null) => void;
  paramsCacheRef: React.MutableRefObject<Map<string, ParamsSnapshot>>;
  cacheKey: (broker: string, strategy: string) => string;
}

export function useBatchRouteState(input: UseBatchRouteStateInput): UseBatchRouteStateReturn {
  const { orders, routes, open, onOpenChange, onComplete } = input;

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
  // Shared start/end time for all selected brokers (HH:MM:SS).
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [releaseTime, setReleaseTime] = useState('');
  // Per-broker allocation ratios (%). Keyed by broker code.
  const [ratios, setRatios] = useState<Record<string, number>>({});

  // ── Broker ratio helpers ───────────────────────────────────────────────
  const ratioSum = useMemo(
    () => Object.values(ratios).reduce((s, v) => s + v, 0),
    [ratios],
  );
  const ratioTotalValid = ratioSum === 100;
  const setRatioForBroker = (broker: string, value: number) => {
    if (!Number.isFinite(value) || value <= 0) return;
    setRatios(prev => ({ ...prev, [broker]: Math.round(value) }));
  };
  const resetRatios = () => {
    if (selectedBrokers.length === 0) return;
    const N = selectedBrokers.length;
    const base = Math.floor(100 / N);
    const rem = 100 - base * N;
    const next: Record<string, number> = {};
    selectedBrokers.forEach((b, i) => { next[b] = base + (i < rem ? 1 : 0); });
    setRatios(next);
  };

  // ── Refs ───────────────────────────────────────────────────────────────
  const prevBrokersRef = useRef<string[]>([]);
  const paramsBuildersRef = useRef<Map<string, ParamsBuilder>>(new Map());
  const paramsCacheRef = useRef<Map<string, ParamsSnapshot>>(new Map());
  const cacheKey = (broker: string, strategy: string) => `${broker}#${strategy}`;
  const fieldSettersRef = useRef<Map<string, FieldSetter>>(new Map());
  const prevOpenRef = useRef(false);

  // ── Ref-based registrations ────────────────────────────────────────────
  const registerFieldSetter = useCallback(
    (broker: string, setter: FieldSetter | null) => {
      if (setter === null) fieldSettersRef.current.delete(broker);
      else fieldSettersRef.current.set(broker, setter);
    },
    [],
  );
  const registerParamsBuilder = useCallback(
    (broker: string, builder: ParamsBuilder | null) => {
      if (builder === null) paramsBuildersRef.current.delete(broker);
      else paramsBuildersRef.current.set(broker, builder);
    },
    [],
  );

  // ── Routed (placed) quantity per parent order ─────────────────────────
  //  Sum of each pending route's `amount`, keyed by parent sequence. Only
  //  statuses in PENDING_ROUTE_STATUSES still consume parent capacity —
  //  terminal routes (FILLED/CANCEL/DONE/REJECTED…) release their amount back
  //  to idle. Mirrors backend batch_route_service.pending_route_statuses so
  //  user UI and server agree on what counts as "already routed".
  const routedAmountByOrder = useMemo(() => {
    const map: Record<string, number> = {};
    if (!routes || routes.length === 0) return map;
    for (const r of routes) {
      if (!PENDING_ROUTE_STATUSES.has(r.status)) continue;
      const oid = String(r.sequence);
      const a = Number(r.amount ?? 0);
      if (!Number.isFinite(a) || a <= 0) continue;
      map[oid] = (map[oid] ?? 0) + a;
    }
    return map;
  }, [routes]);

  //  Idle shares are locked at dialog-open time: the streaming `routes` feed
  //  keeps updating as batch routing proceeds, but allocation capacity must
  //  stay frozen so already-computed splits don't shift mid-flight.
  const [idleByOrder, setIdleByOrder] = useState<Record<string, number>>({});

  const effectiveRemainingOf = useCallback(
    (o: Order): number => idleByOrder[o.id] ?? 0,
    [idleByOrder],
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

  const visibleBrokers = useMemo(() => {
    if (allBrokers.length === 0) return [];
    const markets = Array.from(new Set(
      orders.map(o => deriveMarketKey(o.exchange, o.currency)).filter(Boolean) as string[],
    ));
    if (markets.length === 0) return allBrokers;
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

  const isBrokerAllowedFor = useCallback(
    (broker: string, o: Order): boolean => {
      const market = deriveMarketKey(o.exchange, o.currency);
      const filtered = applyMappingFilter([broker], allowedBrokersFor(market));
      return filtered.includes(broker);
    },
    [allowedBrokersFor],
  );

  // ── Ratio reconciliation on selectedBrokers change ─────────────────────
  useEffect(() => {
    if (!open) return;
    const prev = prevBrokersRef.current;
    if (
      prev.length === selectedBrokers.length &&
      prev.every((b, i) => b === selectedBrokers[i])
    ) return;
    prevBrokersRef.current = [...selectedBrokers];
    setRatios(prev => {
      const next = { ...prev };
      for (const b of selectedBrokers) {
        if (!(b in next)) next[b] = 0;
      }
      for (const b of Object.keys(next)) {
        if (!selectedBrokers.includes(b)) delete next[b];
      }
      const hasZero = selectedBrokers.some(b => (next[b] ?? 0) === 0);
      if (hasZero && selectedBrokers.length > 0) {
        const N = selectedBrokers.length;
        const base = Math.floor(100 / N);
        const rem = 100 - base * N;
        selectedBrokers.forEach((b_, i) => { next[b_] = base + (i < rem ? 1 : 0); });
      }
      return next;
    });
  }, [selectedBrokers, open]);

  // ── Reset on dialog open ────────────────────────────────────────────────
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
      setStartTime('');
      setEndTime('');
      setReleaseTime('');
      paramsBuildersRef.current.clear();
      paramsCacheRef.current.clear();
      const init: Record<string, RowState> = {};
      const idle: Record<string, number> = {};
      for (const o of orders) {
        init[o.id] = { selected: true, allocations: {} };
        const routed = routedAmountByOrder[o.id] ?? 0;
        idle[o.id] = Math.max(0, o.quantity - routed);
      }
      setIdleByOrder(idle);
      setRows(init);
    }
    prevOpenRef.current = open;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // ── Reconcile rows when parent order list refreshes ────────────────────
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
  useEffect(() => {
    if (!open) return;
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const allocs: Record<string, AllocState> = {};
        selectedBrokers.forEach((b) => {
          const existing = r.allocations[b];
          allocs[b] = existing
            ? existing
            : { qty: '0', violations: [] };
        });
        next[oid] = { selected: r.selected, allocations: allocs };
      }
      for (const b of Array.from(paramsBuildersRef.current.keys())) {
        if (selectedBrokers.includes(b)) continue;
        const builder = paramsBuildersRef.current.get(b);
        const strat = brokerStrategies[b] || '';
        if (builder && strat) {
          try {
            const snap = builder();
            if (snap) paramsCacheRef.current.set(cacheKey(b, strat), snap);
          } catch { /* swallow */ }
        }
        paramsBuildersRef.current.delete(b);
      }
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBrokers, open]);

  // ── Selectors ───────────────────────────────────────────────────────────
  const selectedOrders = useMemo(
    () => orders.filter(o => rows[o.id]?.selected),
    [orders, rows],
  );

  const orderMarkets = useMemo(() => {
    const m = new Set<string>();
    for (const o of selectedOrders) {
      const key = deriveMarketKey(o.exchange, o.currency);
      if (key) m.add(key);
    }
    return Array.from(m);
  }, [selectedOrders]);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrders, rows, selectedBrokers]);

  // ── Mutations ───────────────────────────────────────────────────────────
  const toggleBroker = (b: string) => {
    setSelectedBrokers(prev => {
      if (prev.includes(b)) return prev.filter(x => x !== b);
      return [...prev, b];
    });
    setBrokerStrategies(prev => {
      if (b in prev) return prev;
      const def = defaultStrategyFor(strategiesFor(b), b);
      return { ...prev, [b]: def };
    });
  };

  const setBrokerStrategy = (b: string, s: string) => {
    setBrokerStrategies(prev => ({ ...prev, [b]: s }));
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

  // ── Quick-fill actions ──────────────────────────────────────────────────
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

  const applyTimeToAll = () => {
    if (selectedBrokers.length === 0) {
      setError('Pick at least one broker first.');
      return;
    }
    if (startTime && !isValidTimeFormat(startTime)) {
      setError('Start time must be in HH:MM:SS format.');
      return;
    }
    if (endTime && !isValidTimeFormat(endTime)) {
      setError('End time must be in HH:MM:SS format.');
      return;
    }
    if (!startTime && !endTime) {
      setError('Enter a start time and/or end time.');
      return;
    }
    setError('');
    for (const b of selectedBrokers) {
      const strat = brokerStrategies[b] || '';
      const setter = fieldSettersRef.current.get(b);
      if (!setter) continue;
      if (startTime) {
        const fieldName = getStartTimeField(b, strat);
        if (fieldName) setter(fieldName, startTime);
      }
      if (endTime) {
        const fieldName = getEndTimeField(b, strat);
        if (fieldName) setter(fieldName, endTime);
      }
    }
  };

  const applyRatios = () => {
    if (selectedBrokers.length === 0 || selectedOrders.length === 0) return;
    setRows(prev => {
      const next: Record<string, RowState> = {};
      for (const [oid, r] of Object.entries(prev)) {
        if (!r.selected) { next[oid] = r; continue; }
        const o = orders.find(x => x.id === oid);
        if (!o) { next[oid] = r; continue; }
        const remain = effectiveRemainingOf(o);
        const lot = lotSizeOf(o);
        const totalLots = Math.floor(remain / lot);
        const allocs: Record<string, AllocState> = {};
        if (totalLots <= 0) {
          selectedBrokers.forEach(b => {
            const cur = r.allocations[b];
            allocs[b] = {
              qty: '0',
              violations: cur?.violations ?? [],
              status: cur?.status,
              message: cur?.message,
              routeId: cur?.routeId,
            };
          });
        } else {
          const rawLots = selectedBrokers.map(b => (ratios[b] ?? 0) / 100 * totalLots);
          const baseLots = rawLots.map(v => Math.floor(v));
          const used = baseLots.reduce((s, v) => s + v, 0);
          const extra = totalLots - used;

          if (extra > 0) {
            const indices = selectedBrokers
              .map((_, i) => i)
              .sort((a, b) => (rawLots[b] - baseLots[b]) - (rawLots[a] - baseLots[a]));
            for (let i = 0; i < extra; i++) baseLots[indices[i]] += 1;
          }

          selectedBrokers.forEach((b, i) => {
            const cur = r.allocations[b];
            allocs[b] = {
              qty: String(baseLots[i] * lot),
              violations: cur?.violations ?? [],
              status: cur?.status,
              message: cur?.message,
              routeId: cur?.routeId,
            };
          });
        }
        next[oid] = { ...r, allocations: allocs };
      }
      return next;
    });
  };

  // ── Build the API request payload ───────────────────────────────────────
  const buildRequest = (dryRun: boolean): BatchRouteOrderRequest => {
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
        if (!dryRun && alloc?.status === 'BLOCKED') continue;
        const strat = brokerStrategies[b] || '';
        const rt = releaseTime ? hhmmToEmsxInt(releaseTime) : null;
        const override: Partial<BatchRouteOrderRequest['template']> & {
          quantity?: number;
        } = {
          broker: b,
          quantity: qty,
          orderType: o.orderType,
          ...(strat ? { strategy: strat } : {}),
          ...(rt !== null ? { releaseTime: rt } : {}),
        };
        if ((o.orderType === 'LIMIT' || o.orderType === 'STOP_LIMIT') && o.price != null) {
          override.price = o.price;
        }
        if ((o.orderType === 'STOP' || o.orderType === 'STOP_LIMIT') && o.stopPrice != null) {
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

  // ── Validation gate ─────────────────────────────────────────────────────
  const canValidate = useMemo(() => {
    if (selectedOrders.length === 0) return false;
    if (selectedBrokers.length === 0) return false;
    if (orderMarkets.length > 1) return false;
    for (const o of selectedOrders) {
      const r = rows[o.id];
      if (!r) return false;
      const lot = lotSizeOf(o);
      let total = 0;
      let anyPositive = false;
      for (const b of selectedBrokers) {
        const q = computeAllocQty(r.allocations[b]);
        if (q <= 0) continue;
        if (lot > 1 && q % lot !== 0) return false;
        anyPositive = true;
        total += q;
      }
      if (!anyPositive) return false;
      if (total > effectiveRemainingOf(o)) return false;
    }
    return true;
  }, [selectedOrders, selectedBrokers, rows, effectiveRemainingOf, orderMarkets]);

  // ── Derived result details ──────────────────────────────────────────────
  const blockedDetails = useMemo(() => {
    const out: { orderId: string; symbol: string; broker: string; message?: string; violations: Violation[] }[] = [];
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
          message: alloc.message,
          violations: alloc.violations ?? [],
        });
      }
    }
    return out;
  }, [orders, rows]);

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

  const warnDetails = useMemo(() => {
    const out: { orderId: string; symbol: string; broker: string; violations: Violation[] }[] = [];
    const orderById: Record<string, Order> = {};
    for (const o of orders) orderById[o.id] = o;
    for (const [oid, row] of Object.entries(rows)) {
      const o = orderById[oid];
      if (!o) continue;
      for (const [broker, alloc] of Object.entries(row.allocations)) {
        if (alloc.status !== 'SUCCESS') continue;
        const warns = (alloc.violations ?? []).filter(v => v.severity === 'WARN');
        if (warns.length === 0) continue;
        out.push({ orderId: oid, symbol: o.symbol, broker, violations: warns });
      }
    }
    return out;
  }, [orders, rows]);

  // ── Apply results back onto allocation state ────────────────────────────
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

  // ── Workflow actions ────────────────────────────────────────────────────
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
    // Auto-set volume cap for each broker based on allocation ratio
    const INTEGER_CAP_BROKERS = new Set(['EQ-CITI', 'EQ-JPM', 'EQ-UBS', 'EQ-SEB']);
    for (const b of selectedBrokers) {
      const r = ratios[b] ?? 0;
      if (r <= 0) continue;
      const raw = VOLUME_CAP_MULTIPLIER * r / 100;
      const rounded3 = Math.round(raw * 1000) / 1000;
      const cap = INTEGER_CAP_BROKERS.has(b)
        ? Math.max(1, Math.round(rounded3))
        : Math.max(1, Math.round(rounded3 * 10) / 10);
      const capStr = INTEGER_CAP_BROKERS.has(b) ? String(cap) : cap.toFixed(1);
      const strat = brokerStrategies[b] || '';
      const fieldName = getVolumeCapField(b, strat);
      if (fieldName) {
        const setter = fieldSettersRef.current.get(b);
        if (setter) setter(fieldName, capStr);
      }
    }
    setSummary(res.data);
    setPhase('review');
    if (res.data.blocked > 0) {
      setError('Some destinations failed pre-trade checks. See the banner for which broker on which order; edit qty and Validate again, or proceed to Submit (blocked items will be skipped).');
    }
  };

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
    try {
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
    } catch (err) {
      setError(`Submission error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
    setPhase('result');
  };

  const close = () => {
    if (phase === 'submitting') return;
    if (phase === 'result') onComplete?.();
    onOpenChange(false);
  };

  const editable = phase === 'configure' || phase === 'review';

  // ────────────────────────────────────────────────────────────────────────
  return {
    // Raw state
    selectedBrokers, brokerStrategies, tif, notes, rows, phase, error,
    progress, summary, customPct, startTime, endTime, releaseTime, ratios,
    // State setters
    setTif, setNotes, setCustomPct, setStartTime, setEndTime, setReleaseTime, setPhase,
    // Ratio helpers
    ratioSum, ratioTotalValid, setRatioForBroker, resetRatios,
    // Derived / computed
    routedAmountByOrder, effectiveRemainingOf, allBrokers, visibleBrokers,
    strategiesFor, isBrokerAllowedFor, selectedOrders, orderMarkets,
    totalDestinations, canValidate, blockedDetails, failedDetails, warnDetails,
    // Computed helpers
    computeAllocQty, rowTotalQty,
    // Mutations
    toggleBroker, setBrokerStrategy, patchRow, patchAlloc,
    // Quick-fill / ratio actions
    applyPercentQty, applyPercentToBroker, applyTimeToAll, applyRatios,
    // Workflow actions
    buildRequest, runValidation, runSubmit, close,
    // Misc
    editable, registerParamsBuilder, registerFieldSetter, paramsCacheRef, cacheKey,
  };
}
