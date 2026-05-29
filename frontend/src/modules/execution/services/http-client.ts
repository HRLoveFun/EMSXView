/** Shared HTTP client infrastructure for all execution API calls. */

import type { BatchOperationItemResult, BatchOperationResult } from '@execution/types';
import { API_BASE_URL, getAuthHeaders, toErrorString, getToken, TOKEN_KEY } from '@shared/services/http-client';

// Re-export shared core utilities and config
export { apiFetch, getToken, getAuthHeaders, toErrorString, API_BASE_URL, TOKEN_KEY } from '@shared/services/http-client';

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

// ============================================================
// Token management
// ============================================================

export const tokenService = {
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  getToken,
  clearToken: () => localStorage.removeItem(TOKEN_KEY),
};
