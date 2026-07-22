/**
 * useExecutionMutations — all handle* mutation callbacks for the execution view.
 *
 * Each mutation wraps the corresponding API call, manages loading state,
 * updates inflight mutation tracking, and surfaces toast feedback.
 */

import { useCallback } from 'react';
import { apiService } from '@execution/services/execution-api';
import { clearAllCaches } from '@execution/lib';
import type {
  BatchUpdateRequest,
  CancelRouteRequest,
  ModifyOrderRequest,
  ModifyRouteRequest,
  Order,
  RouteOrderRequest,
} from '@execution/types';
import type { Toast } from '@shared/types';

interface UseExecutionMutationsOptions {
  setAllOrders: React.Dispatch<React.SetStateAction<Order[]>>;
  setSelectedOrders: React.Dispatch<React.SetStateAction<Set<string>>>;
  setIsLoading: React.Dispatch<React.SetStateAction<boolean>>;
  fetchOrders: () => Promise<void>;
  fetchOrdersAndRoutes: () => Promise<void>;
  fetchTraderInfo: (forceRefresh?: boolean) => Promise<void>;
  inflightMutationsRef: React.MutableRefObject<number>;
  refreshInflightRef: React.MutableRefObject<boolean>;
  onToast: (type: Toast['type'], message: string) => void;
}

export function useExecutionMutations({
  setAllOrders,
  setSelectedOrders,
  setIsLoading,
  fetchOrders,
  fetchOrdersAndRoutes,
  fetchTraderInfo,
  inflightMutationsRef,
  refreshInflightRef,
  onToast,
}: UseExecutionMutationsOptions) {
  // ── Refresh ────────────────────────────────────────────────────────────
  const handleRefresh = useCallback(async () => {
    if (refreshInflightRef.current) return;
    refreshInflightRef.current = true;
    setIsLoading(true);
    try {
      const response = await apiService.refreshOrders();
      if (response.success && response.data) {
        setAllOrders(response.data);
        setSelectedOrders(new Set());
        onToast('success', 'Orders refreshed successfully');
      } else {
        onToast('error', response.error || 'Failed to refresh orders');
      }
      // 后端已重新订阅 EMSX，再拉取一次订单+路由完整快照，确保前端与 EMSX 对齐
      await fetchOrdersAndRoutes();
      await fetchTraderInfo(true);
    } catch (error) {
      onToast('error', 'Network error while refreshing orders');
      console.error('Refresh error:', error);
    } finally {
      setIsLoading(false);
      refreshInflightRef.current = false;
    }
  }, [fetchOrdersAndRoutes, fetchTraderInfo, onToast, setAllOrders, setSelectedOrders, setIsLoading, refreshInflightRef]);

  // ── Batch Update ───────────────────────────────────────────────────────
  const handleBatchUpdate = useCallback(async (request: BatchUpdateRequest) => {
    setIsLoading(true);
    try {
      const response = await apiService.batchUpdate(request);
      if (response.success && response.data) {
        const result = response.data;
        if (result.success) {
          onToast('success', result.message || 'Batch update successful');
        } else {
          onToast('error', result.message || 'Some orders failed to update');
        }
        await fetchOrders();
        setSelectedOrders(new Set());
      } else {
        onToast('error', response.error || 'Batch update failed');
      }
    } catch (error) {
      onToast('error', 'Network error during batch update');
      console.error('Batch update error:', error);
    } finally {
      setIsLoading(false);
    }
  }, [fetchOrders, onToast, setSelectedOrders, setIsLoading]);

  // ── Selection ──────────────────────────────────────────────────────────
  const handleSelectionChange = useCallback((selectedIds: Set<string>) => {
    setSelectedOrders(selectedIds);
  }, [setSelectedOrders]);

  const handleClearSelection = useCallback(() => {
    setSelectedOrders(new Set());
  }, [setSelectedOrders]);

  // ── Cache ──────────────────────────────────────────────────────────────
  const handleClearCache = useCallback(() => {
    clearAllCaches();
    fetchTraderInfo(true);
    onToast('info', 'Cache cleared');
  }, [fetchTraderInfo, onToast]);

  // ── Cancel Route ───────────────────────────────────────────────────────
  const handleCancelRoute = useCallback(async (request: CancelRouteRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.cancelRoute(request);
      if (response.success) {
        onToast('success', `Route ${request.routeId} cancel request sent`);
      } else {
        onToast('error', response.error || `Failed to cancel route ${request.routeId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while cancelling route');
      console.error('Cancel route error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [inflightMutationsRef, onToast]);

  // ── Modify Route ───────────────────────────────────────────────────────
  const handleModifyRoute = useCallback(async (request: ModifyRouteRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.modifyRoute(request);
      if (response.success) {
        onToast('success', `Route ${request.routeId} modify request sent`);
      } else {
        onToast('error', response.error || `Failed to modify route ${request.routeId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while modifying route');
      console.error('Modify route error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [inflightMutationsRef, onToast]);

  // ── Modify Order ───────────────────────────────────────────────────────
  const handleModifyOrder = useCallback(async (request: ModifyOrderRequest) => {
    inflightMutationsRef.current += 1;
    try {
      const response = await apiService.modifyOrder(request);
      if (response.success) {
        onToast('success', `Order ${request.orderId} modified successfully`);
        await fetchOrders();
      } else {
        onToast('error', response.error || `Failed to modify order ${request.orderId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while modifying order');
      console.error('Modify order error:', error);
    } finally {
      inflightMutationsRef.current = Math.max(0, inflightMutationsRef.current - 1);
    }
  }, [fetchOrders, inflightMutationsRef, onToast]);

  // ── Route Order ────────────────────────────────────────────────────────
  const handleRouteOrder = useCallback(async (request: RouteOrderRequest) => {
    try {
      const response = await apiService.routeOrder(request);
      if (response.success) {
        onToast('success', `Route created for order ${request.orderId} to broker ${request.broker}`);
        await fetchOrders();
      } else {
        onToast('error', response.error || `Failed to route order ${request.orderId}`);
      }
    } catch (error) {
      onToast('error', 'Network error while routing order');
      console.error('Route order error:', error);
    }
  }, [fetchOrders, onToast]);

  return {
    handleRefresh,
    handleBatchUpdate,
    handleSelectionChange,
    handleClearSelection,
    handleClearCache,
    handleCancelRoute,
    handleModifyRoute,
    handleModifyOrder,
    handleRouteOrder,
  };
}
