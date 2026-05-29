/**
 * Startup status API — lightweight HTTP client for backend health checks.
 *
 * Extracted from @execution/services to break the Shell → Execution coupling.
 * Both the App shell (use-startup-status hook) and Execution module (orders-api)
 * should import from here.
 */
import type { ApiResponse, StartupStatusSnapshot } from '@shared/types';
import { apiFetch } from './http-client';

/** Fetch the backend startup/health status. */
export async function getStartupStatus(): Promise<ApiResponse<StartupStatusSnapshot>> {
  return apiFetch<StartupStatusSnapshot>('/api/startup-status');
}
