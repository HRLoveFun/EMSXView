/** Batch-route-order dialog module — barrel export. */
export { BatchRouteOrderDialog } from '../batch-route-order-dialog';
export { useBatchRouteState } from './use-batch-route-state';
export type { UseBatchRouteStateInput, UseBatchRouteStateReturn } from './use-batch-route-state';

// Sub-components (for reuse in other contexts)
export { BrokerSelectionPanel } from './broker-selection-panel';
export { BrokerStrategySection } from './broker-strategy-section';
export { BatchRouteToolbar } from './batch-route-toolbar';
export { QuickFillToolbar } from './quick-fill-toolbar';
export { BrokerRatioBar } from './broker-ratio-bar';
export { OrderAllocationTable } from './order-allocation-table';
export { ResultFeedback } from './result-feedback';

// Re-export existing sub-components
export { OrderRow } from './order-row';
export { BrokerStrategyParamsEditor } from './broker-strategy-params-editor';

// Types & utilities
export * from './types';
export * from './utils';
