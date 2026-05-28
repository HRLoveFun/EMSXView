/** Shared HTTP client infrastructure for all execution API calls. */

import type { ApiResponse } from '@shared/types';
import type { BatchOperationItemResult, BatchOperationResult } from '@execution/types';
import { getToken, getAuthHeaders } from '@shared/services/token-service';
import { tokenService } from '@shared/services/token-service';

// ============================================================
// Configuration
// ============================================================

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

// Re-export for backward compatibility
export { getToken, getAuthHeaders, tokenService };

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

// ============================================================
// NDJSON streaming (batch endpoints)
// ============================================================

const NDJSON_STREAM_TIMEOUT_MS = 300_000;

export async function streamNdjsonBatch(
  path: string,
  body: unknown,
  onItem: (item: BatchOperationItemResult) => void,
  onSummary: (summary: BatchOperationResult) => void,
): Promise<{ success: boolean; error?: string }> {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), NDJSON_STREAM_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      const text = await response.text();
      let msg = response.statusText;
      try {
        const j = JSON.parse(text);
        msg = toErrorString(j.error ?? j.detail ?? msg);
      } catch { /* keep statusText */ }
      return { success: false, error: msg };
    }
    if (!response.body) {
      return { success: false, error: 'Response body is empty' };
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl = buffer.indexOf('\n');
      while (nl >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        nl = buffer.indexOf('\n');
        if (!line) continue;
        try {
          const obj = JSON.parse(line);
          if (obj && typeof obj === 'object' && 'summary' in obj) {
            try { onSummary(obj.summary as BatchOperationResult); } catch { /* callback error */ }
          } else {
            try { onItem(obj as BatchOperationItemResult); } catch { /* callback error */ }
          }
        } catch { /* ignore malformed line */ }
      }
    }
    const tail = buffer.trim();
    if (tail) {
      try {
        const obj = JSON.parse(tail);
        if (obj && typeof obj === 'object' && 'summary' in obj) {
          try { onSummary(obj.summary as BatchOperationResult); } catch { /* callback error */ }
        } else {
          try { onItem(obj as BatchOperationItemResult); } catch { /* callback error */ }
        }
      } catch { /* ignore */ }
    }
    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Network error';
    if (err instanceof DOMException && err.name === 'AbortError') {
      return { success: false, error: `Request timed out after ${NDJSON_STREAM_TIMEOUT_MS / 1000}s` };
    }
    return { success: false, error: message };
  } finally {
    clearTimeout(timerId);
  }
}


