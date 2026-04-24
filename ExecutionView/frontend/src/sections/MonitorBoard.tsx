import { useState, useCallback, useMemo, useEffect, Fragment } from 'react';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Layers,
  RotateCcw,
} from 'lucide-react';
import type { BoolConditionConfig, ConditionConfig } from '@/lib/monitor-conditions';
import {
  HEALTH_PALETTE,
  HEALTH_RANK,
  getOrderHealth,
  isLazyOrder,
  type HealthLevel,
  type LazyContext,
} from '@/lib/health-palette';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { fmtNum, fmtInt, fmtDollar } from '@/lib/format-utils';
import { ORDER_GROUP_BY_OPTIONS, ORDER_GROUP_BY_LABELS, type OrderGroupByValue } from '@/lib/table-constants';
import {
  CONDITION_DEFS,
  DEFAULT_CONDITIONS,
  matchesAnyCondition,
  getOrderFlags,
  type MonitorConditions,
  type ConditionId,
} from '@/lib/monitor-conditions';
import type { Order, OrderStatus, Route } from '@/types';

// ─── Constants ───────────────────────────────────────────────────────────────
const TOTAL_COLS = 26; // Health strip + 25 data cols (see ColHeader list below)

// ─── Status badge ────────────────────────────────────────────────────────────
function getStatusBadge(status: OrderStatus) {
  const map: Record<OrderStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }> = {
    NEW:            { variant: 'outline' },
    ASSIGN:         { variant: 'outline', className: 'border-cyan-500 text-cyan-600' },
    WORKING:        { variant: 'default', className: 'bg-blue-500/90 hover:bg-blue-600' },
    PARTIAL:        { variant: 'default', className: 'bg-amber-500/90 hover:bg-amber-600' },
    FILLED:         { variant: 'default', className: 'bg-emerald-500/90 hover:bg-emerald-600' },
    CANCELLED:      { variant: 'secondary' },
    COMPLETED:      { variant: 'default', className: 'bg-green-600/90 hover:bg-green-700' },
    QUEUED:         { variant: 'default', className: 'bg-purple-500/90 hover:bg-purple-600' },
    SUSPENDED:      { variant: 'default', className: 'bg-orange-500/90 hover:bg-orange-600' },
    PENDING_CANCEL: { variant: 'destructive', className: 'bg-red-400/90' },
    REJECTED:       { variant: 'destructive' },
    SENT:           { variant: 'default', className: 'bg-sky-500/90 hover:bg-sky-600' },
  };
  const s = map[status] ?? { variant: 'outline' as const };
  return <Badge variant={s.variant} className={`text-[10px] px-1.5 py-0 leading-4 ${s.className ?? ''}`}>{status}</Badge>;
}

// ─── Threshold input (commit on blur / Enter) ───────────────────────────────
function ThresholdInput({
  value, onChange, step, className, disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  step: number;
  className?: string;
  disabled?: boolean;
}) {
  const [local, setLocal] = useState(String(value));
  useEffect(() => { setLocal(String(value)); }, [value]);

  const commit = () => {
    const v = parseFloat(local);
    if (!isNaN(v) && v >= 0) onChange(v);
    else setLocal(String(value));
  };

  return (
    <input
      type="number"
      value={local}
      onChange={e => setLocal(e.target.value)}
      onBlur={commit}
      onKeyDown={e => { if (e.key === 'Enter') { commit(); (e.target as HTMLInputElement).blur(); } }}
      min={0}
      step={step}
      disabled={disabled}
      className={`h-6 rounded border border-input bg-background px-1.5 text-xs text-foreground tabular-nums
        focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 ${className ?? ''}`}
    />
  );
}

// ─── Types ───────────────────────────────────────────────────────────────────
type SortField = keyof Order | 'flagCount' | null;
type SortDirection = 'asc' | 'desc';
interface SortConfig { field: SortField; direction: SortDirection }

interface Subgroup { key: string; label: string; orders: Order[] }
interface CondGroup {
  conditionId: ConditionId;
  label: string;
  color: string;
  bgColor: string;
  count: number;
  subgroups: Subgroup[];
}

// ─── Props ───────────────────────────────────────────────────────────────────
interface MonitorBoardProps {
  allOrders: Order[];
  allRoutes?: Route[];
  isLoading: boolean;
  conditions: MonitorConditions;
  onConditionsChange: (c: MonitorConditions) => void;
  onOpenConditionsSettings?: () => void;
  onExceptionCountChange?: (count: number) => void;
}

// ─── Component ───────────────────────────────────────────────────────────────
export function MonitorBoard({
  allOrders,
  allRoutes = [],
  isLoading,
  conditions,
  onConditionsChange,
  onOpenConditionsSettings,
  onExceptionCountChange,
}: MonitorBoardProps) {
  // ── Condition helpers ──────────────────────────────────────────────────────
  const toggleCondition = useCallback((id: ConditionId) => {
    onConditionsChange({ ...conditions, [id]: { ...conditions[id], enabled: !conditions[id].enabled } });
  }, [conditions, onConditionsChange]);

  const updateThreshold = useCallback((id: ConditionId, value: number) => {
    onConditionsChange({ ...conditions, [id]: { ...conditions[id], threshold: value } });
  }, [conditions, onConditionsChange]);

  const resetConditions = useCallback(() => {
    onConditionsChange(structuredClone(DEFAULT_CONDITIONS));
  }, [onConditionsChange]);

  // ── Sort / Subgroup state ─────────────────────────────────────────────────
  const [sortConfig, setSortConfig] = useState<SortConfig>({ field: null, direction: 'asc' });
  const [groupBy, setGroupBy] = useState<OrderGroupByValue>('exchange');
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(
    () => new Set([
      'c:__critical__',
      'c:__lazy__',
      ...CONDITION_DEFS.map(d => `c:${d.id}`),
    ]),
  );

  // ── Total unique alert count ──────────────────────────────────────────────
  const totalAlerts = useMemo(
    () => allOrders.filter(o => matchesAnyCondition(o, conditions)).length,
    [allOrders, conditions],
  );

  // ── Lazy / critical context (shared across health resolution + synthetic groups) ──
  const idleShareByOrderId = useMemo(() => {
    const placedByOrderId = new Map<string, number>();
    for (const r of allRoutes) {
      // Route is keyed to parent order by `sequence`. We rely on a (sequence→orderId)
      // lookup via allOrders; fall back to string match on `order.id === sequence`.
      // Build only what's needed below; avoid O(N*M) by pre-indexing orders by id.
      const key = String(r.sequence);
      placedByOrderId.set(key, (placedByOrderId.get(key) ?? 0) + (r.amount ?? 0));
    }
    const result = new Map<string, number>();
    for (const o of allOrders) {
      const placed = placedByOrderId.get(o.id) ?? 0;
      result.set(o.id, Math.max(0, o.quantity - placed));
    }
    return result;
  }, [allOrders, allRoutes]);

  const lazyCtx = useMemo<LazyContext>(() => ({ idleShareByOrderId }), [idleShareByOrderId]);

  const criticalOrders = useMemo(
    () => allOrders.filter(o => o.status === 'REJECTED' || o.status === 'PENDING_CANCEL'),
    [allOrders],
  );
  const lazyOrders = useMemo(
    () => allOrders.filter(o => isLazyOrder(o, lazyCtx)),
    [allOrders, lazyCtx],
  );

  // Report exception count upward (for Tab badges). Includes critical + condition-hit.
  useEffect(() => {
    if (!onExceptionCountChange) return;
    const exceptions = new Set<string>();
    for (const o of criticalOrders) exceptions.add(o.id);
    for (const o of allOrders) if (matchesAnyCondition(o, conditions)) exceptions.add(o.id);
    onExceptionCountChange(exceptions.size);
  }, [criticalOrders, allOrders, conditions, onExceptionCountChange]);

  // ── Sort all flagged orders once ──────────────────────────────────────────
  const sortedFlagged = useMemo(() => {
    const flagged = allOrders.filter(o => matchesAnyCondition(o, conditions));
    const { field, direction } = sortConfig;
    if (!field) return flagged;
    return [...flagged].sort((a, b) => {
      let va: unknown, vb: unknown;
      if (field === 'flagCount') {
        va = getOrderFlags(a, conditions).length;
        vb = getOrderFlags(b, conditions).length;
      } else {
        va = a[field]; vb = b[field];
      }
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'string' && typeof vb === 'string')
        return direction === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      if (typeof va === 'number' && typeof vb === 'number')
        return direction === 'asc' ? va - vb : vb - va;
      return 0;
    });
  }, [allOrders, conditions, sortConfig]);

  // ── Condition-first grouping with optional subgroups ──────────────────────
  const condGroups = useMemo<CondGroup[]>(() => {
    const result: CondGroup[] = [];

    // ── Synthetic pinned groups (always first) ──
    const makeSubgroups = (orders: Order[]): Subgroup[] => {
      if (orders.length === 0) return [];
      if (groupBy === 'none') return [{ key: '__all__', label: '', orders }];
      const map = new Map<string, Order[]>();
      for (const o of orders) {
        const k = String((o as unknown as Record<string, unknown>)[groupBy] ?? '(empty)');
        if (!map.has(k)) map.set(k, []);
        map.get(k)!.push(o);
      }
      return Array.from(map.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, orders]) => ({ key, label: `${ORDER_GROUP_BY_LABELS[groupBy]}: ${key}`, orders }));
    };
    if (criticalOrders.length > 0) {
      result.push({
        conditionId: '__critical__' as ConditionId,
        label: `\u26a0 Critical (REJECTED / PENDING_CANCEL)`,
        color: 'text-red-700',
        bgColor: 'bg-red-100',
        count: criticalOrders.length,
        subgroups: makeSubgroups(criticalOrders),
      });
    }
    if (lazyOrders.length > 0 && conditions.lazy?.enabled) {
      result.push({
        conditionId: '__lazy__' as ConditionId,
        label: `Lazy Orders (status not {WORKING, QUEUED, COMPLETED, FILLED, SUSPENDED} or idle share > 0)`,
        color: 'text-sky-700',
        bgColor: 'bg-sky-100',
        count: lazyOrders.length,
        subgroups: makeSubgroups(lazyOrders),
      });
    }

    for (const def of CONDITION_DEFS) {
      const cfg = conditions[def.id];
      if (!cfg.enabled) continue;

      const matching = sortedFlagged.filter(o => {
        if (def.isBool) {
          const boolCfg = cfg as BoolConditionConfig;
          return def.test(o, 0, boolCfg.value);
        }
        return def.test(o, (cfg as ConditionConfig).threshold);
      });
      if (matching.length === 0) continue;

      let subgroups: Subgroup[];
      if (groupBy === 'none') {
        subgroups = [{ key: '__all__', label: '', orders: matching }];
      } else {
        const map = new Map<string, Order[]>();
        for (const o of matching) {
          const k = String((o as unknown as Record<string, unknown>)[groupBy] ?? '(empty)');
          if (!map.has(k)) map.set(k, []);
          map.get(k)!.push(o);
        }
        subgroups = Array.from(map.entries())
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([key, orders]) => ({ key, label: `${ORDER_GROUP_BY_LABELS[groupBy]}: ${key}`, orders }));
      }

      result.push({
        conditionId: def.id,
        label: def.groupLabel((cfg as ConditionConfig).threshold),
        color: def.color,
        bgColor: def.bgColor,
        count: matching.length,
        subgroups,
      });
    }
    return result;
  }, [conditions, sortedFlagged, groupBy, criticalOrders, lazyOrders]);

  // ── Expand / collapse ─────────────────────────────────────────────────────
  const toggleKey = useCallback((key: string) => {
    setExpandedKeys(prev => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  }, []);

  const handleGroupByChange = useCallback((v: OrderGroupByValue) => {
    setGroupBy(v);
    // Keep condition-level keys, drop subgroup keys
    setExpandedKeys(prev => {
      const n = new Set<string>();
      for (const k of prev) { if (k.startsWith('c:')) n.add(k); }
      return n;
    });
  }, []);

  // ── Sort ──────────────────────────────────────────────────────────────────
  const toggleSort = useCallback((field: SortField) => {
    setSortConfig(prev =>
      prev.field === field
        ? { field, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
        : { field, direction: 'asc' },
    );
  }, []);

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortConfig.field !== field) return <ArrowUpDown className="h-3 w-3 opacity-40" />;
    return sortConfig.direction === 'asc'
      ? <ArrowUp className="h-3 w-3 text-primary" />
      : <ArrowDown className="h-3 w-3 text-primary" />;
  };

  const ColHeader = ({ label, field, className = '' }: { label: string; field: SortField; className?: string }) => (
    <th
      className={`px-2 py-1.5 text-left text-[11px] font-semibold text-muted-foreground uppercase tracking-wider cursor-pointer select-none whitespace-nowrap hover:text-foreground ${className}`}
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">{label}<SortIcon field={field} /></span>
    </th>
  );

  // ── Helper functions ──────────────────────────────────────────────────────
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPmNote = (order: Order) => {
    const parts: string[] = [];
    if (order.notes) parts.push(order.notes);
    if (parts.length > 0) return parts.join('');
    return order.execInstruction || order.customNote1 || order.customNote2
      || order.customNote3 || order.customNote4 || order.customNote5 || '';
  };

  const getStrategyDetail = (order: Order) => {
    if (!order.strategyType) return '';
    const parts: string[] = [];
    if (order.strategyPartRate != null) parts.push(`Rate: ${order.strategyPartRate.toFixed(0)}%`);
    if (order.strategyStyle) parts.push(`Style: ${order.strategyStyle}`);
    if (order.strategyStartTime) parts.push(`Start: ${order.strategyStartTime}`);
    if (order.strategyEndTime) parts.push(`End: ${order.strategyEndTime}`);
    return parts.join(' | ');
  };

  // ── Order row renderer ────────────────────────────────────────────────────
  const renderOrderRow = (order: Order, keyPrefix: string) => {
    const flags = getOrderFlags(order, conditions);
    const health: HealthLevel = getOrderHealth({ order, conditions, ctx: lazyCtx });
    const palette = HEALTH_PALETTE[health];
    const rowTint = HEALTH_RANK[health] >= HEALTH_RANK.warning ? palette.rowClass : '';
    return (
      <TooltipProvider key={`${keyPrefix}-${order.id}`} delayDuration={200}>
        <tr className={`border-b border-border/50 hover:bg-muted/30 transition-colors ${rowTint}`}>
          <td className="w-1 p-0">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className={`h-full min-h-[22px] w-1 ${palette.stripClass}`} aria-label={`Health: ${palette.label}`} />
              </TooltipTrigger>
              <TooltipContent side="right" className="text-xs">Health: {palette.label}</TooltipContent>
            </Tooltip>
          </td>
          <td className="px-2 py-1.5 font-mono text-xs">{order.id}</td>
          <td className="px-2 py-1.5 font-mono font-medium whitespace-nowrap">{order.symbol}</td>
          <td className={`px-2 py-1.5 font-medium ${order.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>{order.side}</td>
          <td className="px-2 py-1.5">{getStatusBadge(order.status)}</td>
          <td className="px-2 py-1.5 text-muted-foreground">{order.orderType}</td>
          <td className={`px-2 py-1.5 text-right font-mono ${order.side === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="cursor-help">{fmtInt(order.quantity)}</span>
              </TooltipTrigger>
              <TooltipContent>
                <div className="text-xs space-y-1">
                  <div>Total: {order.quantity.toLocaleString()}</div>
                  <div className="text-green-400">Filled: {order.filledQuantity.toLocaleString()}</div>
                  <div className="text-yellow-400">Remaining: {order.remainingQuantity.toLocaleString()}</div>
                </div>
              </TooltipContent>
            </Tooltip>
          </td>
          <td className="px-2 py-1.5 text-right font-mono">{order.quantity > 0 ? order.percentFilled.toFixed(0) + '%' : ''}</td>
          <td className="px-2 py-1.5 text-right font-mono">{order.price != null ? fmtNum(order.price) : '—'}</td>
          <td className="px-2 py-1.5 text-right font-mono">{fmtNum(order.avgPrice)}</td>
          <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{order.arrivalPrice != null ? fmtNum(order.arrivalPrice) : ''}</td>
          <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{order.lastPrice != null ? fmtNum(order.lastPrice) : ''}</td>
          <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{order.mktVwap != null ? fmtNum(order.mktVwap) : ''}</td>
          <td className={`px-2 py-1.5 text-right font-mono ${(() => {
            const dv = order.dollarValueUsd;
            const lo = conditions.dollarValueLow;
            const hi = conditions.dollarValueHigh;
            return dv != null && ((lo.enabled && dv < lo.threshold) || (hi.enabled && dv > hi.threshold))
              ? 'text-red-600 font-semibold' : '';
          })()}`}>
            {order.dollarValueUsd != null ? fmtDollar(order.dollarValueUsd) : '—'}
          </td>
          <td className={`px-2 py-1.5 text-right font-mono ${
            order.pctChange != null
              ? (order.pctChange > 0 ? 'text-emerald-600' : order.pctChange < 0 ? 'text-red-600' : '')
              : ''
          }`}>
            {order.pctChange != null ? (order.pctChange > 0 ? '+' : '') + order.pctChange.toFixed(2) + '%' : ''}
          </td>
          <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{order.adv5d != null ? order.adv5d.toLocaleString() : ''}</td>
          <td className="px-2 py-1.5 truncate max-w-[100px]">
            <Tooltip><TooltipTrigger asChild><span>{order.portfolio}</span></TooltipTrigger>
              <TooltipContent side="top"><p>{order.portfolio}</p></TooltipContent>
            </Tooltip>
          </td>
          <td className="px-2 py-1.5">{order.trader}</td>
          <td className="px-2 py-1.5">{order.exchange || ''}</td>
          <td className="px-2 py-1.5">{order.currency}</td>
          <td className="px-2 py-1.5 text-right font-mono text-muted-foreground">{order.fxRate != null ? order.fxRate.toFixed(4) : ''}</td>
          <td className="px-2 py-1.5 text-xs font-medium">{order.strategyType || ''}</td>
          <td className="px-2 py-1.5 text-xs text-muted-foreground truncate max-w-[120px]" title={getStrategyDetail(order)}>{getStrategyDetail(order)}</td>
          <td className="px-2 py-1.5 text-xs truncate max-w-[150px]" title={getPmNote(order)}>{getPmNote(order)}</td>
          <td className="px-2 py-1.5 text-muted-foreground text-xs whitespace-nowrap">{formatDate(order.createdAt)}</td>
          <td className="px-2 py-1.5">
            <div className="flex flex-wrap gap-1">
              {flags.map((f, i) => (
                <span key={i} className={`inline-block px-1.5 py-0 rounded text-[10px] leading-4 font-medium ${f.bgColor} ${f.color}`}>
                  {f.label}
                </span>
              ))}
            </div>
          </td>
        </tr>
      </TooltipProvider>
    );
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Header bar */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <span className="text-sm font-semibold">Monitor Board</span>
          <Badge variant="secondary" className="text-xs">{totalAlerts} alerts</Badge>
        </div>
      </div>

      {/* ── Active conditions summary (readonly) ── */}
      <div className="border-b border-border px-4 py-2 bg-secondary/20 flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Active conditions:</span>
        {CONDITION_DEFS.filter(def => conditions[def.id].enabled).length === 0 && (
          <span className="text-[11px] text-muted-foreground italic">(none)</span>
        )}
        {CONDITION_DEFS.map(def => {
          const cfg = conditions[def.id];
          if (!cfg.enabled) return null;
          const label = def.isBool
            ? def.groupLabel(0)
            : def.groupLabel((cfg as ConditionConfig).threshold);
          return (
            <span
              key={def.id}
              className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${def.bgColor} ${def.color}`}
            >
              {label}
            </span>
          );
        })}
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={resetConditions}
            className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
            title="Reset conditions to defaults"
          >
            <RotateCcw className="h-3 w-3" />Reset
          </button>
          {onOpenConditionsSettings && (
            <button
              onClick={onOpenConditionsSettings}
              className="text-[10px] text-primary hover:underline"
            >
              Edit in Settings \u2192
            </button>
          )}
        </div>
      </div>

      {/* ── Subgroup-by bar ── */}
      <div className="border-b border-border px-4 py-1.5 bg-secondary/30 flex items-center gap-2 text-xs text-muted-foreground">
        <Layers className="h-3.5 w-3.5" />
        <span>Subgroup by</span>
        <Select value={groupBy} onValueChange={v => handleGroupByChange(v as OrderGroupByValue)}>
          <SelectTrigger className="h-6 text-xs w-36 border-0 bg-transparent focus:ring-0 p-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ORDER_GROUP_BY_OPTIONS.map(opt => (
              <SelectItem key={opt.value} value={opt.value} className="text-xs">{opt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* ── Table ── */}
      <ScrollArea className="max-h-[calc(100vh-380px)]">
        <table className="w-full min-w-max text-xs">
          <thead className="sticky top-0 bg-card z-10 border-b border-border">
            <tr>
              <th className="w-1 p-0" aria-label="Health" />
              <ColHeader label="Order ID" field="id" />
              <ColHeader label="Ticker"    field="symbol" />
              <ColHeader label="Side"      field="side" />
              <ColHeader label="Status"    field="status" />
              <ColHeader label="Type"      field="orderType" />
              <ColHeader label="Qty"       field="quantity" className="text-right" />
              <ColHeader label="%Filled"   field="percentFilled" className="text-right" />
              <ColHeader label="Limit Px"  field="price" className="text-right" />
              <ColHeader label="Avg Px"    field="avgPrice" className="text-right" />
              <ColHeader label="Arr Px"    field="arrivalPrice" className="text-right" />
              <ColHeader label="Last Px"   field="lastPrice" className="text-right" />
              <ColHeader label="Ivl VWAP"  field="mktVwap" className="text-right" />
              <ColHeader label="$Value"    field="dollarValueUsd" className="text-right" />
              <ColHeader label="%Change"   field="pctChange" className="text-right" />
              <ColHeader label="ADV 5D"    field="adv5d" className="text-right" />
              <ColHeader label="Portfolio" field="portfolio" />
              <ColHeader label="Trader"    field="trader" />
              <ColHeader label="Exchange"  field="exchange" />
              <ColHeader label="Ccy"       field="currency" />
              <ColHeader label="FX Rate"   field="fxRate" className="text-right" />
              <ColHeader label="Strategy"  field="strategyType" />
              <ColHeader label="Strat Params" field="strategyPartRate" />
              <ColHeader label="PM Note"   field="notes" />
              <ColHeader label="Created"   field="createdAt" />
              <th className="px-2 py-1.5 text-left text-[11px] font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                Flags
              </th>
            </tr>
          </thead>
          <tbody>
            {isLoading && totalAlerts === 0 && condGroups.length === 0 && (
              <tr><td colSpan={TOTAL_COLS} className="py-8 text-center text-muted-foreground">Loading…</td></tr>
            )}
            {!isLoading && condGroups.length === 0 && (
              <tr><td colSpan={TOTAL_COLS} className="py-8 text-center text-muted-foreground">No orders match monitor conditions</td></tr>
            )}

            {condGroups.map(cg => {
              const condKey = `c:${cg.conditionId}`;
              const isCondExpanded = expandedKeys.has(condKey);
              return (
                <Fragment key={cg.conditionId}>
                  {/* Condition-group header */}
                  <tr
                    className="cursor-pointer select-none transition-colors"
                    onClick={() => toggleKey(condKey)}
                  >
                    <td colSpan={TOTAL_COLS} className={`px-3 py-1.5 ${cg.bgColor}`}>
                      <div className="flex items-center gap-2">
                        {isCondExpanded
                          ? <ChevronDown className={`h-3.5 w-3.5 ${cg.color}`} />
                          : <ChevronRight className={`h-3.5 w-3.5 ${cg.color}`} />}
                        <span className={`font-semibold text-xs ${cg.color}`}>{cg.label}</span>
                        <Badge variant="secondary" className="text-[10px]">{cg.count}</Badge>
                      </div>
                    </td>
                  </tr>

                  {/* Expanded content */}
                  {isCondExpanded && cg.subgroups.map(sg => {
                    // No subgrouping → render orders directly
                    if (groupBy === 'none') {
                      return sg.orders.map(o => renderOrderRow(o, cg.conditionId));
                    }
                    // With subgrouping → render subgroup header + expandable orders
                    const subKey = `s:${cg.conditionId}:${sg.key}`;
                    const isSubExpanded = expandedKeys.has(subKey);
                    return (
                      <Fragment key={sg.key}>
                        <tr
                          className="bg-muted/40 cursor-pointer select-none hover:bg-muted/60 transition-colors"
                          onClick={() => toggleKey(subKey)}
                        >
                          <td colSpan={TOTAL_COLS} className="px-6 py-1">
                            <div className="flex items-center gap-2">
                              {isSubExpanded
                                ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
                              <span className="font-medium text-xs">{sg.label}</span>
                              <span className="text-muted-foreground/60 text-[10px]">({sg.orders.length})</span>
                            </div>
                          </td>
                        </tr>
                        {isSubExpanded && sg.orders.map(o => renderOrderRow(o, `${cg.conditionId}:${sg.key}`))}
                      </Fragment>
                    );
                  })}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </ScrollArea>
    </div>
  );
}
