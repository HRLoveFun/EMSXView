import { useState } from 'react';
import { ListOrdered, GitBranch } from 'lucide-react';
import { OrderTable } from './OrderTable';
import { RouteTable } from './RouteTable';
import { BatchOperationPanel } from './BatchOperationPanel';
import type { Order, Route, OrderFilters, BatchUpdateRequest, CancelRouteRequest, ModifyRouteRequest, ModifyOrderRequest, RouteOrderRequest } from '@/types';

interface ExecutionBoardProps {
  orders: Order[];
  allOrders: Order[];
  routes: Route[];
  selectedOrders: Set<string>;
  onSelectionChange: (selectedIds: Set<string>) => void;
  isLoading: boolean;
  filters: OrderFilters;
  onFilterChange: (filters: OrderFilters) => void;
  currentTrader: string;
  onBatchUpdate: (request: BatchUpdateRequest) => Promise<void>;
  onClearSelection: () => void;
  onCancelRoute?: (request: CancelRouteRequest) => Promise<void>;
  onModifyRoute?: (request: ModifyRouteRequest) => Promise<void>;
  onModifyOrder?: (request: ModifyOrderRequest) => Promise<void>;
  onRouteOrder?: (request: RouteOrderRequest) => Promise<void>;
  onRefresh?: () => Promise<void>;
}

type ExecutionTab = 'orders' | 'routes';

export function ExecutionBoard({
  orders,
  allOrders,
  routes,
  selectedOrders,
  onSelectionChange,
  isLoading,
  filters,
  onFilterChange,
  currentTrader,
  onBatchUpdate,
  onClearSelection,
  onCancelRoute,
  onModifyRoute,
  onModifyOrder,
  onRouteOrder,
  onRefresh,
}: ExecutionBoardProps) {
  const [activeTab, setActiveTab] = useState<ExecutionTab>('orders');

  return (
    <div className="space-y-4">
      {/* Sub-tab navigation */}
      <div className="flex items-center gap-1 border-b border-border">
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-2 ${
            activeTab === 'orders'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => setActiveTab('orders')}
        >
          <ListOrdered className="h-4 w-4" />
          Orders ({orders.length})
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px flex items-center gap-2 ${
            activeTab === 'routes'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => setActiveTab('routes')}
        >
          <GitBranch className="h-4 w-4" />
          Routes ({routes.length})
        </button>
      </div>

      {/* Tab content */}
      {activeTab === 'orders' ? (
        <>
          <OrderTable
            orders={orders}
            allOrders={allOrders}
            selectedOrders={selectedOrders}
            onSelectionChange={onSelectionChange}
            isLoading={isLoading}
            filters={filters}
            onFilterChange={onFilterChange}
            onModifyOrder={onModifyOrder}
            onRouteOrder={onRouteOrder}
            currentTrader={currentTrader}
          />
          <BatchOperationPanel
            selectedCount={selectedOrders.size}
            onBatchUpdate={onBatchUpdate}
            onClearSelection={onClearSelection}
            isLoading={isLoading}
          />
        </>
      ) : (
        <RouteTable
          routes={routes}
          isLoading={isLoading}
          currentTrader={currentTrader}
          onCancelRoute={onCancelRoute}
          onModifyRoute={onModifyRoute}
          onRefresh={onRefresh}
        />
      )}
    </div>
  );
}
