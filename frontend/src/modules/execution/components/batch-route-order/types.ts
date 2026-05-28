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
  effectiveRemaining: number;
  pendingWorking: number;
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

/** Route statuses that still consume parent order capacity. */
export const PENDING_ROUTE_STATUSES = new Set([
  'SENT', 'WORKING', 'PARTFILLED', 'QUEUED', 'HOLD',
  'CXLREQ', 'CXLREJ', 'CXLREP', 'CXLRPRQ', 'CXLRPRJ',
  'REPPEN', 'A-SENT', 'OA-SENT',
]);
