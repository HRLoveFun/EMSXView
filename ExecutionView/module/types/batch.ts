/**
 * Batch operation types.
 *
 * P3-SRP: Extracted from types/index.ts.
 */

import type { ModifyRouteRequest, RouteOrderRequest } from './order';

export type UpdateableField = 'price' | 'quantity' | 'timeInForce' | 'status';

export interface BatchUpdateRequest {
  orderIds: string[];
  field: UpdateableField;
  value: string | number;
}

export interface BatchUpdateResponse {
  success: boolean;
  updatedCount: number;
  failedOrders?: { orderId: string; reason: string }[];
  message?: string;
}

export interface BatchRouteOrderItem {
  orderId: string;
  clientKey?: string;
  override?: Partial<Omit<RouteOrderRequest, 'orderId'>>;
  /** DL-25/219：预填来源决策与交易员改写原因 */
  decisionId?: string;
  rewriteReason?: string;
}

/** Trader rewrite reason codes (DL-25/219) */
export const REWRITE_REASON_OPTIONS = [
  'UNCHANGED',
  'BROKER_CHANGED',
  'QUANTITY_CHANGED',
  'PARAMS_CHANGED',
  'EXTRA_ROUTE',
] as const;

export type RewriteReason = (typeof REWRITE_REASON_OPTIONS)[number];

/** Shadow decision record shape returned by GET /api/routing-decisions */
export interface ShadowDecisionCandidate {
  broker: string;
  quantity: number;
  strategy_params?: Record<string, unknown>;
  participation_pct?: number | null;
  rationale?: string;
}

export interface ShadowDecisionRecord {
  decision_id: string;
  order_id: string;
  as_of?: string;
  source?: string;
  schema_version?: string;
  payload: {
    candidates?: ShadowDecisionCandidate[];
    source?: string;
    rationale?: string;
    intent?: string;
    schema_version?: string;
  };
}

export interface BatchRouteOrderRequest {
  template: Partial<Omit<RouteOrderRequest, 'orderId'>>;
  items: BatchRouteOrderItem[];
  dryRun?: boolean;
}

export interface BatchModifyRouteItem {
  sequence: number;
  routeId: number;
  clientKey?: string;
  override?: Partial<Omit<ModifyRouteRequest, 'sequence' | 'routeId'>>;
}

export interface BatchModifyRouteRequest {
  template: Partial<Omit<ModifyRouteRequest, 'sequence' | 'routeId'>>;
  items: BatchModifyRouteItem[];
  dryRun?: boolean;
}

export type BatchOperationItemStatus = 'SUCCESS' | 'BLOCKED' | 'FAILED';

export interface BatchOperationItemResult {
  key: string;
  status: BatchOperationItemStatus;
  message: string;
  violations: import('./compliance').Violation[];
  routeId?: number | null;
}

export interface BatchOperationResult {
  total: number;
  succeeded: number;
  blocked: number;
  failed: number;
  items: BatchOperationItemResult[];
}
