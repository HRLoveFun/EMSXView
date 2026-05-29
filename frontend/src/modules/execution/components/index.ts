/**
 * Execution module components — barrel re-export.
 *
 * P3-SRP: Provides a unified import surface for all execution components.
 * Individual components can still be imported directly for tree-shaking.
 *
 * Usage:
 *   import { OrderTable, RouteTable } from '@execution/components';
 */

// ── Core execution components ─────────────────────────────────────────

export { OrderTable } from '../views/OrderTable';
export { RouteTable } from '../views/RouteTable';
export { BatchOperationPanel } from '../views/BatchOperationPanel';

// ── Dialogs ───────────────────────────────────────────────────────────

export { CancelRouteDialog } from './cancel-route-dialog';
export { ModifyAmountDialog } from './modify-amount-dialog';
export { ModifyLimitPriceDialog } from './modify-limit-price-dialog';
export { ModifyOrderTypeDialog } from './modify-order-type-dialog';
export { OrderModifyDialog } from './order-modify-dialog';
export { AlgoLaunchDialog } from './algo-launch-dialog';
export { BrokerStrategyDialog } from './broker-strategy-dialog';
export { RateDiagnosticDialog } from './rate-diagnostic-dialog';
export { StrategyDataManagerDialog } from './strategy-data-manager-dialog';

// ── Batch operation components ────────────────────────────────────────

export { BatchOperationDialogs } from './batch-operation-dialogs';
export { BatchRouteOrderDialog } from './batch-route-order-dialog';
export { BatchRouteOrder } from './batch-route-order';

// ── Route components ──────────────────────────────────────────────────

export { RouteActionMenu } from './route-action-menu';
export { RouteModifyDialogs } from './route-modify-dialogs';
export { UnifiedModifyRouteDialog } from './unified-modify-route-dialog';

// ── Route Plan & Engine components ────────────────────────────────────

export { RoutePlanManager } from './route-plan-manager';
export { SubOrderReviewPanel } from './sub-order-review-panel';

// ── Broker & Mapping components ───────────────────────────────────────

export { BrokerStrategyFields } from './broker-strategy-fields';
export { MarketBrokerMappingSection } from './market-broker-mapping-section';

// ── Compliance ────────────────────────────────────────────────────────

export { ComplianceViolation } from './compliance-violation';

// ── Shared UI ─────────────────────────────────────────────────────────

export { OrderStatusBadge } from './order-status-badge';

// ── Filters (sub-package) ─────────────────────────────────────────────

export {
  MultiSelectFilterPopover,
  SideFilterPopover,
  TextFilterPopover,
} from './filters';
