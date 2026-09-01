/** Shared types for BatchRouteOrderDialog sub-components. */

import type { Order, Route, TimeInForce, Violation } from '@execution/types';

export const tifOptions: { value: TimeInForce; label: string }[] = [
  { value: 'DAY', label: 'Day' },
  { value: 'GTC', label: 'GTC' },
  { value: 'IOC', label: 'IOC' },
  { value: 'FOK', label: 'FOK' },
];

export const QUICK_PCT_PRESETS = [25, 50, 75, 100] as const;

export type Phase = 'configure' | 'review' | 'submitting' | 'result';
export type AllocStatus = 'BLOCKED' | 'SUCCESS' | 'FAILED';

export interface AllocState {
  qty: string;
  violations: Violation[];
  status?: AllocStatus;
  message?: string;
  routeId?: number | null;
}

export interface RowState {
  selected: boolean;
  allocations: Record<string, AllocState>;
}

export interface BatchRouteOrderDialogProps {
  orders: Order[];
  routes?: Route[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onComplete?: () => void;
}

export interface OrderRowProps {
  order: Order;
  row: RowState;
  lot: number;
  total: number;
  /** 该单可路由额度（idle）= 父单剩余量 − 在途路由量 */
  effectiveRemaining: number;
  /** 父单剩余量（remainingQuantity），idle 的被减数基准 */
  orderRemaining: number;
  /** 已在途（pending）的路由量 */
  routedAmount: number;
  overAlloc: boolean;
  anyAlloc: boolean;
  selectedBrokers: string[];
  isBrokerAllowedFor: (broker: string, o: Order) => boolean;
  onPatchRow: (patch: Partial<RowState>) => void;
  onPatchAlloc: (broker: string, patch: Partial<AllocState>) => void;
  editable: boolean;
  phase: Phase;
  ratios: Record<string, number>;
}

import type { useStrategyFields } from '@execution/components/broker-strategy-fields';

export interface BrokerStrategyParamsEditorProps {
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
  getCachedSnapshot: (broker: string, strategy: string) => ReturnType<
    ReturnType<typeof useStrategyFields>['toStrategyParams']
  > | undefined;
  disabled: boolean;
  registerFieldSetter?: (
    broker: string,
    setter: ((fieldName: string, value: string) => void) | null,
  ) => void;
}

/**
 * Route statuses that still consume parent order capacity.
 * 唯一真相源在 `@execution/lib/route-capacity`（后端 pending_route_statuses 同步），
 * 此处仅 re-export 以保持既有 import 路径不变。
 */
export { PENDING_ROUTE_STATUSES } from '@execution/lib/route-capacity';

// ── Sub-component prop interfaces ─────────────────────────────────────────

export interface BrokerSelectionPanelProps {
  visibleBrokers: string[];
  selectedBrokers: string[];
  editable: boolean;
  toggleBroker: (b: string) => void;
  strategiesFor: (b: string) => string[];
  defaultStrategyFor: (strategies: string[], broker?: string) => string;
  onSelectAll: () => void;
  onDeselectAll: () => void;
}

export interface BrokerStrategySectionProps {
  selectedBrokers: string[];
  brokerStrategies: Record<string, string>;
  strategiesFor: (b: string) => string[];
  setBrokerStrategy: (b: string, s: string) => void;
  registerParamsBuilder: BrokerStrategyParamsEditorProps['registerParamsBuilder'];
  registerFieldSetter: BrokerStrategyParamsEditorProps['registerFieldSetter'];
  paramsCacheRef: React.MutableRefObject<Map<string, unknown>>;
  cacheKey: (broker: string, strategy: string) => string;
  editable: boolean;
  defaultStrategyFor: (strategies: string[], broker?: string) => string;
}

export interface BatchRouteToolbarProps {
  tif: TimeInForce;
  notes: string;
  releaseTime: string;
  startTime: string;
  endTime: string;
  editable: boolean;
  selectedBrokers: string[];
  onTifChange: (v: TimeInForce) => void;
  onNotesChange: (v: string) => void;
  onReleaseTimeChange: (v: string) => void;
  onStartTimeChange: (v: string) => void;
  onEndTimeChange: (v: string) => void;
  onApplyTimeToAll: () => void;
}

export interface QuickFillToolbarProps {
  editable: boolean;
  selectedBrokers: string[];
  selectedOrders: Order[];
  customPct: string;
  onCustomPctChange: (v: string) => void;
  onApplyPercentQty: (pct: number) => void;
}

export interface BrokerRatioBarProps {
  selectedBrokers: string[];
  ratios: Record<string, number>;
  ratioSum: number;
  ratioTotalValid: boolean;
  editable: boolean;
  setRatioForBroker: (broker: string, value: number) => void;
  resetRatios: () => void;
  applyRatios: () => void;
}

export interface OrderAllocationTableProps {
  orders: Order[];
  rows: Record<string, RowState>;
  selectedBrokers: string[];
  editable: boolean;
  phase: Phase;
  ratios: Record<string, number>;
  effectiveRemainingOf: (o: Order) => number;
  routedAmountOf: (o: Order) => number;
  isBrokerAllowedFor: (broker: string, o: Order) => boolean;
  patchRow: (oid: string, patch: Partial<RowState>) => void;
  patchAlloc: (oid: string, broker: string, patch: Partial<AllocState>) => void;
  applyPercentToBroker: (broker: string, pct: number) => void;
}

export interface ResultFeedbackProps {
  phase: Phase;
  error: string;
  progress: number;
  summary: { total?: number; succeeded?: number; blocked?: number; failed?: number } | null;
  totalDestinations: number;
  blockedDetails: { orderId: string; symbol: string; broker: string; message?: string; violations: Violation[] }[];
  failedDetails: { orderId: string; symbol: string; broker: string; message: string }[];
  warnDetails: { orderId: string; symbol: string; broker: string; violations: Violation[] }[];
}
