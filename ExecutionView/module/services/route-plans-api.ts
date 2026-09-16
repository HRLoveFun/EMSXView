/** Route-plan & sub-order-proposal API methods. */

import type {
  RoutePlan, CreateRoutePlanRequest, UpdateRoutePlanRequest,
  SubOrderProposal, BatchConfirmRequest, TestMatchResponse,
  BatchRouteOrderRequest, BatchModifyRouteRequest,
  BatchOperationItemResult, BatchOperationResult,
} from '@execution/types';
import type { ApiResponse } from '@shared/types';
import { apiFetch, streamNdjsonBatch } from './http-client';

export const routePlansApi = {
  // ── Route Plan CRUD ───────────────────────────────────────────────────

  async listRoutePlans(enabled?: boolean): Promise<ApiResponse<RoutePlan[]>> {
    const params = enabled !== undefined ? `?enabled=${enabled}` : '';
    return apiFetch<RoutePlan[]>(`/api/route-plans${params}`);
  },

  async createRoutePlan(request: CreateRoutePlanRequest): Promise<ApiResponse<RoutePlan>> {
    return apiFetch<RoutePlan>('/api/route-plans', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async getRoutePlan(planId: number): Promise<ApiResponse<RoutePlan>> {
    return apiFetch<RoutePlan>(`/api/route-plans/${planId}`);
  },

  async updateRoutePlan(planId: number, request: UpdateRoutePlanRequest): Promise<ApiResponse<RoutePlan>> {
    return apiFetch<RoutePlan>(`/api/route-plans/${planId}`, {
      method: 'PUT',
      body: JSON.stringify(request),
    });
  },

  async deleteRoutePlan(planId: number): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/route-plans/${planId}`, { method: 'DELETE' });
  },

  async testMatchRoutePlan(planId: number): Promise<ApiResponse<TestMatchResponse>> {
    return apiFetch<TestMatchResponse>(`/api/route-plans/${planId}/test-match`, { method: 'POST' });
  },

  // ── Route Engine ──────────────────────────────────────────────────────

  async applyRouteEngine(orderId: string, planId?: number): Promise<ApiResponse<SubOrderProposal[]>> {
    const params = planId ? `?plan_id=${planId}` : '';
    return apiFetch<SubOrderProposal[]>(`/api/route-engine/apply/${orderId}${params}`, { method: 'POST' });
  },

  async listSubOrderProposals(status?: string, trader?: string): Promise<ApiResponse<SubOrderProposal[]>> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (trader) params.append('trader', trader);
    const q = params.toString();
    return apiFetch<SubOrderProposal[]>(`/api/sub-order-proposals${q ? `?${q}` : ''}`);
  },

  async confirmProposal(proposalId: number): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/sub-order-proposals/${proposalId}/confirm`, { method: 'POST' });
  },

  async batchConfirmProposals(
    request: BatchConfirmRequest,
    onItem: (item: BatchOperationItemResult) => void,
    onSummary: (summary: BatchOperationResult) => void,
  ): Promise<{ success: boolean; error?: string }> {
    if (request.dryRun) {
      const result = await apiFetch<BatchOperationResult>('/api/sub-order-proposals/batch-confirm', {
        method: 'POST',
        body: JSON.stringify({ ...request, dryRun: true }),
      });
      if (result.success && result.data) {
        onSummary(result.data);
      }
      return { success: result.success, error: result.error };
    }
    return streamNdjsonBatch('/api/sub-order-proposals/batch-confirm', { ...request, dryRun: false }, onItem, onSummary);
  },

  async rejectProposal(proposalId: number): Promise<ApiResponse<void>> {
    return apiFetch<void>(`/api/sub-order-proposals/${proposalId}/reject`, { method: 'POST' });
  },
};

// ============================================================
// Batch Route / Batch Modify methods
// ============================================================

export const batchApi = {
  async dryRunBatchRoute(request: BatchRouteOrderRequest): Promise<ApiResponse<BatchOperationResult>> {
    return apiFetch<BatchOperationResult>('/api/orders/batch-route', {
      method: 'POST',
      body: JSON.stringify({ ...request, dryRun: true }),
    });
  },

  async streamBatchRoute(
    request: BatchRouteOrderRequest,
    onItem: (item: BatchOperationItemResult) => void,
    onSummary: (summary: BatchOperationResult) => void,
  ): Promise<{ success: boolean; error?: string }> {
    return streamNdjsonBatch('/api/orders/batch-route', { ...request, dryRun: false }, onItem, onSummary);
  },

  async dryRunBatchModifyRoutes(request: BatchModifyRouteRequest): Promise<ApiResponse<BatchOperationResult>> {
    return apiFetch<BatchOperationResult>('/api/routes/batch-modify', {
      method: 'POST',
      body: JSON.stringify({ ...request, dryRun: true }),
    });
  },

  async streamBatchModifyRoutes(
    request: BatchModifyRouteRequest,
    onItem: (item: BatchOperationItemResult) => void,
    onSummary: (summary: BatchOperationResult) => void,
  ): Promise<{ success: boolean; error?: string }> {
    return streamNdjsonBatch('/api/routes/batch-modify', { ...request, dryRun: false }, onItem, onSummary);
  },
};
