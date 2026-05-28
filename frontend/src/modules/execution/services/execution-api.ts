/** Execution API — barrel re-exports composing apiService from domain modules. */

import { ordersApi } from './orders-api';
import { routesApi } from './routes-api';
import { brokerApi, cachedBrokerApi } from './broker-api';
import { routePlansApi, batchApi } from './route-plans-api';

// Re-export HTTP client for consumers that need direct access
export { apiFetch, streamNdjsonBatch, tokenService, getToken, getAuthHeaders, toErrorString } from './http-client';

/** Combined API service — maintained for backward compatibility with existing callers. */
export const apiService = {
  // Orders
  ...ordersApi,

  // Routes
  ...routesApi,

  // Broker / Asset
  ...brokerApi,

  // Route Plans + Batch
  ...routePlansApi,
  ...batchApi,
};

/** Cached broker API — maintained for backward compatibility. */
export const cachedApiService = cachedBrokerApi;
