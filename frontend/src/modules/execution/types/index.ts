/**
 * Execution domain types — barrel re-export.
 *
 * P3-SRP: Refactored from a single 550-line file into domain-specific modules.
 * All existing imports from `@execution/types` continue to work unchanged.
 *
 * Domain modules:
 *   types/order.ts            — Order, Route, Filter, Modification types
 *   types/batch.ts            — Batch operation types
 *   types/parent-execution.ts — Parent-child algorithmic execution types
 *   types/broker.ts           — Broker/strategy configuration types
 *   types/route-plan.ts       — Route Plan and RouteEngine types
 *   types/compliance.ts       — Pre-trade compliance types
 */

export * from './order';
export * from './batch';
export * from './parent-execution';
export * from './broker';
export * from './route-plan';
export * from './compliance';
