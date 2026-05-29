/**
 * Shared HTTP client — lightweight fetch wrapper used across modules.
 *
 * Extracted from @execution/services/http-client to break the Shell → Execution coupling.
 * Both the Shared layer and Execution module should import apiFetch from here.
 */

import type { ApiResponse } from '@shared/types';

// ============================================================
// Configuration
// ============================================================

export const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
export const TOKEN_KEY = 'emsx_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  return headers;
}

/** Normalize structured error values to human-readable strings. */
export function toErrorString(err: unknown): string {
  if (typeof err === 'string') return err;
  if (err instanceof Error) return err.message;
  if (Array.isArray(err)) {
    return err.map(e => {
      if (typeof e === 'object' && e !== null) {
        return (e as { msg?: string }).msg ?? JSON.stringify(e);
      }
      return String(e);
    }).join('; ');
  }
  if (typeof err === 'object' && err !== null) {
    const obj = err as Record<string, unknown>;
    return String(obj.msg ?? obj.message ?? obj.error ?? JSON.stringify(err));
  }
  return String(err);
}

/** Lightweight fetch wrapper returning ApiResponse<T>. */
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${path}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: { ...getAuthHeaders(), ...(options.headers ?? {}) },
    });

    const contentType = response.headers.get('content-type') ?? '';
    const hasJsonBody = contentType.includes('application/json');
    const text = await response.text();

    if (!response.ok) {
      if (text && hasJsonBody) {
        try {
          const err = JSON.parse(text);
          const errorMsg = toErrorString(err.error ?? err.detail ?? response.statusText);
          if (response.status === 502 || response.status === 503 || response.status === 504) {
            if (errorMsg.includes('Bloomberg')) {
              return { success: false, error: errorMsg };
            }
            return { success: false, error: `Backend unavailable: ${errorMsg}` };
          }
          return { success: false, error: errorMsg };
        } catch { /* fall through */ }
      }
      if (response.status === 502 || response.status === 503 || response.status === 504) {
        return { success: false, error: 'Backend unavailable — please start the backend service' };
      }
      if (response.status === 500 && (!text || !hasJsonBody)) {
        return { success: false, error: 'Cannot connect to backend (ECONNREFUSED)' };
      }
      return { success: false, error: text || response.statusText };
    }

    if (!text) {
      return { success: true } as ApiResponse<T>;
    }

    const data = JSON.parse(text);
    return data as ApiResponse<T>;
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}
