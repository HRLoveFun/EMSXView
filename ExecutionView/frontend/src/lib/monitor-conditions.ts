/**
 * Shared monitor-condition types, defaults, persistence, and matchers.
 * Used by MonitorBoard (condition panel) and App (toolbar alert count).
 */
import type { Order } from '@/types';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ConditionConfig {
  enabled: boolean;
  threshold: number;
}

export interface BoolConditionConfig {
  enabled: boolean;
  value: boolean;
}

export interface MonitorConditions {
  dollarValueLow:  ConditionConfig;
  dollarValueHigh: ConditionConfig;
  pctChangeBuy:    ConditionConfig;
  pctChangeSell:   ConditionConfig;
  qtyAdvRatio:     ConditionConfig;
  oddLot:          BoolConditionConfig;  // Odd lot orders (quantity < 100)
  /**
   * Lazy order surfacing (evaluated in MonitorBoard with LazyContext — not part
   * of CONDITION_DEFS because it needs runtime context). When enabled, lazy
   * orders appear as a pinned synthetic group on the Monitor Board; when
   * disabled the synthetic group is hidden.
   */
  lazy:            BoolConditionConfig;
}

export type ConditionId = keyof MonitorConditions;

// ─── Defaults ────────────────────────────────────────────────────────────────

export const DEFAULT_CONDITIONS: MonitorConditions = {
  dollarValueLow:  { enabled: true, threshold: 10_000 },
  dollarValueHigh: { enabled: true, threshold: 49_000_000 },
  pctChangeBuy:    { enabled: true, threshold: 4.5 },
  pctChangeSell:   { enabled: true, threshold: 4.5 },
  qtyAdvRatio:     { enabled: true, threshold: 5 },
  oddLot:          { enabled: true, value: true },  // Default: show odd lot orders
  lazy:            { enabled: true, value: true },  // Default: show lazy orders
};

// ─── Persistence ─────────────────────────────────────────────────────────────

const STORAGE_KEY = 'emsx-monitor-conditions';

export function loadConditions(): MonitorConditions {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<MonitorConditions>;
      return {
        dollarValueLow:  { ...DEFAULT_CONDITIONS.dollarValueLow,  ...p.dollarValueLow },
        dollarValueHigh: { ...DEFAULT_CONDITIONS.dollarValueHigh, ...p.dollarValueHigh },
        pctChangeBuy:    { ...DEFAULT_CONDITIONS.pctChangeBuy,    ...p.pctChangeBuy },
        pctChangeSell:   { ...DEFAULT_CONDITIONS.pctChangeSell,   ...p.pctChangeSell },
        qtyAdvRatio:     { ...DEFAULT_CONDITIONS.qtyAdvRatio,     ...p.qtyAdvRatio },
        oddLot:          { ...DEFAULT_CONDITIONS.oddLot,          ...p.oddLot },
        lazy:            { ...DEFAULT_CONDITIONS.lazy,            ...p.lazy },
      };
    }
  } catch { /* corrupted — use defaults */ }
  return structuredClone(DEFAULT_CONDITIONS);
}

export function saveConditions(c: MonitorConditions): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(c)); } catch { /* ignore */ }
}

// ─── Condition definitions ───────────────────────────────────────────────────

function fmtThreshold(v: number): string {
  if (v >= 1_000_000) {
    const m = v / 1_000_000;
    return Number.isInteger(m) ? `${m}M` : `${parseFloat(m.toFixed(1))}M`;
  }
  if (v >= 1_000) {
    const k = v / 1_000;
    return Number.isInteger(k) ? `${k}K` : `${parseFloat(k.toFixed(1))}K`;
  }
  return v.toLocaleString();
}

export interface ConditionDef {
  id: ConditionId;
  label: string;
  unit: string;
  groupLabel: (threshold: number) => string;
  color: string;
  bgColor: string;
  test: (order: Order, threshold: number, boolValue?: boolean) => boolean;
  isBool?: boolean;  // True for boolean conditions without threshold
  boolValue?: boolean;  // The boolean value to test against (for isBool conditions)
}

export const CONDITION_DEFS: ConditionDef[] = [
  {
    id: 'dollarValueLow',
    label: '$Value <',
    unit: '',
    groupLabel: t => `$Value < ${fmtThreshold(t)}`,
    color: 'text-amber-700',
    bgColor: 'bg-amber-100',
    test: (o, t) => { const dv = o.dollarValueUsd; return dv != null && dv < t; },
  },
  {
    id: 'dollarValueHigh',
    label: '$Value >',
    unit: '',
    groupLabel: t => `$Value > ${fmtThreshold(t)}`,
    color: 'text-red-700',
    bgColor: 'bg-red-100',
    test: (o, t) => { const dv = o.dollarValueUsd; return dv != null && dv > t; },
  },
  {
    id: 'pctChangeBuy',
    label: '%Chg >',
    unit: '% (Buy)',
    groupLabel: t => `%Chg > ${t}% (Buy)`,
    color: 'text-rose-700',
    bgColor: 'bg-rose-100',
    test: (o, t) => o.pctChange != null && o.side === 'BUY' && o.pctChange > t,
  },
  {
    id: 'pctChangeSell',
    label: '%Chg < \u2212',
    unit: '% (Sell)',
    groupLabel: t => `%Chg < \u2212${t}% (Sell)`,
    color: 'text-rose-700',
    bgColor: 'bg-rose-100',
    test: (o, t) => o.pctChange != null && o.side === 'SELL' && o.pctChange < -t,
  },
  {
    id: 'qtyAdvRatio',
    label: 'Qty/ADV >',
    unit: '%',
    groupLabel: t => `Qty/ADV > ${t}%`,
    color: 'text-violet-700',
    bgColor: 'bg-violet-100',
    test: (o, t) => o.adv5d != null && o.adv5d > 0 && (o.quantity / o.adv5d) * 100 > t,
  },
  {
    id: 'oddLot',
    label: 'Odd Lot (JP)',
    unit: '',
    groupLabel: () => 'Odd Lot (JP)',
    color: 'text-blue-700',
    bgColor: 'bg-blue-100',
    test: (o: Order, threshold: number) => {
      void threshold;
      // isOddLot is computed by backend based on PX_ROUND_LOT_SIZE
      // Only applies to Japan market (JP exchange)
      return o.isOddLot === true;
    },
    isBool: true,
    boolValue: true,
  },
];

// ─── Matchers ────────────────────────────────────────────────────────────────

/** Check if an order matches any enabled condition. */
export function matchesAnyCondition(order: Order, conditions: MonitorConditions): boolean {
  return CONDITION_DEFS.some(def => {
    const cfg = conditions[def.id];
    if (!cfg.enabled) return false;
    if (def.isBool) {
      // Boolean condition: use value property instead of threshold
      const boolCfg = cfg as BoolConditionConfig;
      return def.test(order, 0, boolCfg.value);
    }
    return def.test(order, (cfg as ConditionConfig).threshold);
  });
}

/** Per-order flag badges for the Flags column. */
export interface MonitorFlag {
  label: string;
  color: string;
  bgColor: string;
}

export function getOrderFlags(order: Order, conditions: MonitorConditions): MonitorFlag[] {
  const flags: MonitorFlag[] = [];
  for (const def of CONDITION_DEFS) {
    const cfg = conditions[def.id];
    if (!cfg.enabled) continue;
    if (def.isBool) {
      // Boolean condition: use value property instead of threshold
      const boolCfg = cfg as BoolConditionConfig;
      if (!def.test(order, 0, boolCfg.value)) continue;
      flags.push({ label: def.groupLabel(0), color: def.color, bgColor: def.bgColor });
    } else {
      if (!def.test(order, (cfg as ConditionConfig).threshold)) continue;
      let label: string;
      if (def.id === 'pctChangeBuy' || def.id === 'pctChangeSell') {
        label = `%Chg ${order.pctChange!.toFixed(2)}%`;
      } else if (def.id === 'qtyAdvRatio') {
        const ratio = (order.quantity / order.adv5d!) * 100;
        label = `Qty/ADV ${ratio.toFixed(1)}%`;
      } else {
        label = def.groupLabel((cfg as ConditionConfig).threshold);
      }
      flags.push({ label, color: def.color, bgColor: def.bgColor });
    }
  }
  return flags;
}
