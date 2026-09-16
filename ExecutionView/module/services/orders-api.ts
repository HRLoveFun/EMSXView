/** Order-related API methods. */

import type {
  Order, OrderFilters, BatchUpdateRequest, BatchUpdateResponse,
  ModifyOrderRequest, RouteOrderRequest,
} from '@execution/types';
import type { ApiResponse, StartupStatusSnapshot } from '@shared/types';
import { getStartupStatus } from '@shared/services/startup-api';
import { apiFetch } from './http-client';

export const ordersApi = {
  async getOrders(filters?: OrderFilters): Promise<ApiResponse<Order[]>> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== '' && value !== null) {
          params.append(key, String(value));
        }
      });
    }
    const query = params.toString();
    return apiFetch<Order[]>(`/api/orders${query ? `?${query}` : ''}`);
  },

  async batchUpdate(request: BatchUpdateRequest): Promise<ApiResponse<BatchUpdateResponse>> {
    return apiFetch<BatchUpdateResponse>('/api/orders/batch-update', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async refreshOrders(): Promise<ApiResponse<Order[]>> {
    return apiFetch<Order[]>('/api/orders/refresh');
  },

  async getOrdersStatus(): Promise<ApiResponse<{
    init_paint_done: boolean;
    order_count: number;
    route_count: number;
    subscription_failed: boolean;
    is_connected: boolean;
  }>> {
    return apiFetch('/api/orders/status');
  },

  async modifyOrder(request: ModifyOrderRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/orders/modify', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async routeOrder(request: RouteOrderRequest): Promise<ApiResponse<{
    success: boolean;
    orderId: string;
    routeId?: number;
    broker: string;
    quantity: number;
  }>> {
    return apiFetch('/api/orders/route', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async getStartupStatus(): Promise<ApiResponse<StartupStatusSnapshot>> {
    return getStartupStatus();
  },

  async checkConnection(): Promise<ApiResponse<{ status: 'connected' | 'disconnected' }>> {
    const result = await getStartupStatus();
    if (result.success && result.data) {
      const s = result.data.bloomberg.status === 'connected' ? 'connected' : 'disconnected';
      return { success: true, data: { status: s } };
    }
    return { success: true, data: { status: 'disconnected' } };
  },
};
