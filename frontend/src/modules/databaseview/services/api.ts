import type {
  IntegrityResponse,
  OverviewResponse,
  SampleResponse,
  SchemaResponse,
  SummaryResponse,
  TriggerUpdateResponse,
  UpdateStatusResponse,
} from '../types';

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

export async function fetchOverview(): Promise<OverviewResponse> {
  const response = await fetch(`${API_BASE_URL}/api/db/overview`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<OverviewResponse>;
}

export async function fetchSummary(
  key: string,
  dateLimit = 800,
): Promise<SummaryResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/db/${encodeURIComponent(key)}/summary?date_limit=${dateLimit}`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<SummaryResponse>;
}

export async function fetchIntegrity(key: string): Promise<IntegrityResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/db/${encodeURIComponent(key)}/integrity`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<IntegrityResponse>;
}

export async function triggerUpdate(): Promise<TriggerUpdateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/db/update`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<TriggerUpdateResponse>;
}

export async function fetchUpdateStatus(jobId: string): Promise<UpdateStatusResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/db/update-status/${encodeURIComponent(jobId)}`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<UpdateStatusResponse>;
}

export async function fetchTableSchema(
  key: string,
  table: string,
): Promise<SchemaResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/db/${encodeURIComponent(key)}/tables/${encodeURIComponent(table)}/schema`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<SchemaResponse>;
}

export async function fetchTableSample(
  key: string,
  table: string,
  limit = 50,
): Promise<SampleResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/db/${encodeURIComponent(key)}/tables/${encodeURIComponent(table)}/sample?limit=${limit}`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<SampleResponse>;
}