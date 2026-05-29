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
