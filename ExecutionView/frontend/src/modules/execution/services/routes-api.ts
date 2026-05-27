/** Route & market-broker-mapping API methods. */

import type {
  Route, CancelRouteRequest, ModifyRouteRequest,
} from '@execution/types';
import type { ApiResponse } from '@shared/types';
import { apiFetch } from './http-client';

export const routesApi = {
  async getRoutes(): Promise<ApiResponse<Route[]>> {
    return apiFetch<Route[]>('/api/routes');
  },

  async cancelRoute(request: CancelRouteRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/routes/cancel', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async modifyRoute(request: ModifyRouteRequest): Promise<ApiResponse<void>> {
    return apiFetch<void>('/api/routes/modify', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  async diagnoseStrategyRate(): Promise<ApiResponse<{
    summary: {
      totalRoutesWithStrategy: number;
      routesWithRate: number;
      routesMissingRate: number;
      brokerStrategyPairsFullyMissing: number;
      brokerStrategyPairsPartiallyMissing: number;
    };
    groups: Array<{
      broker: string;
      strategyType: string;
      withRate: number;
      withoutRate: number;
      total: number;
      routes: Array<{
        sequence: number;
        routeId: number;
        broker: string;
        strategyType: string;
        strategyStyle: string;
        rate1: number | null;
        rate2: number | null;
        hasRate: boolean;
        status: string;
        ticker: string;
      }>;
    }>;
  }>> {
    return apiFetch('/api/routes/diagnose-strategy-rate');
  },

  async getRouteEnums(): Promise<ApiResponse<{
    orderTypes: Array<{ value: string; label: string; needsLimit: boolean; needsStop: boolean }>;
    tifOptions: Array<{ value: string; label: string }>;
  }>> {
    return apiFetch('/api/routes/reference-enums');
  },

  // ── Market Broker Mapping ──────────────────────────────────────────────

  async getMarketBrokerMapping(): Promise<ApiResponse<{
    updatedAt: string | null;
    rosters: Record<string, string[]>;
    selection: Record<string, Record<string, boolean>>;
  }>> {
    return apiFetch('/api/market-broker-mapping');
  },

  async updateMarketBrokerSelection(selection: Record<string, Record<string, boolean>>): Promise<ApiResponse<unknown>> {
    return apiFetch('/api/market-broker-mapping/selection', {
      method: 'PUT',
      body: JSON.stringify({ selection }),
    });
  },

  async unlockMarketBrokerRow(password: string, market?: string): Promise<ApiResponse<{ unlocked: boolean }>> {
    return apiFetch('/api/market-broker-mapping/unlock', {
      method: 'POST',
      body: JSON.stringify({ password, market }),
    });
  },

  async updateMarketBrokerRoster(market: string, brokers: string[], password: string): Promise<ApiResponse<unknown>> {
    return apiFetch('/api/market-broker-mapping/roster', {
      method: 'PUT',
      body: JSON.stringify({ market, brokers, password }),
    });
  },
};
