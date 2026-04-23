import type { MarketSnapshotPayload } from '../types';

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
const TOKEN_KEY = 'emsx_token';

function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    (headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return body?.detail ?? body?.error ?? `Request failed: ${response.status}`;
}

export async function fetchMarketSnapshot(limit = 25): Promise<MarketSnapshotPayload> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`${API_BASE_URL}/api/marketview/snapshot?${params.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as MarketSnapshotPayload;
}