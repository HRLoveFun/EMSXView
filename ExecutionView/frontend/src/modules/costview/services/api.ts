import type {
  ScorecardReport,
  ScorecardRequestPayload,
  TcaAnalyzeRequest,
  TcaReport,
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

export async function analyzeTca(request: TcaAnalyzeRequest): Promise<TcaReport> {
  const response = await fetch(`${API_BASE_URL}/api/tca/analyze`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as TcaReport;
}

export async function triggerUpdate(): Promise<TriggerUpdateResponse> {
  const response = await fetch(`${API_BASE_URL}/api/tca/trigger-update`, {
    method: 'POST',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json() as Promise<TriggerUpdateResponse>;
}

export async function getUpdateStatus(jobId: string): Promise<UpdateStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/tca/update-status/${encodeURIComponent(jobId)}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  return response.json() as Promise<UpdateStatusResponse>;
}

export async function fetchAllFilteredOrders(
  request: Omit<TcaAnalyzeRequest, 'offset' | 'limit'> & { limit?: number },
): Promise<TcaReport> {
  const pageSize = request.limit ?? 200;
  let offset = 0;
  let totalOrders = 0;
  let generatedAt = new Date().toISOString();
  let filters: TcaReport['filters'] = {
    aggregation: request.aggregation ?? 'per_order',
    limit: pageSize,
    offset: 0,
    ...request.filters,
  };
  const orders: TcaReport['orders'] = [];

  do {
    const page = await analyzeTca({
      ...request,
      limit: pageSize,
      offset,
    });

    totalOrders = page.total_orders;
    generatedAt = page.generated_at;
    filters = page.filters;
    orders.push(...page.orders);
    offset += page.limit;
  } while (orders.length < totalOrders);

  return {
    filters: {
      ...filters,
      limit: orders.length || pageSize,
      offset: 0,
    },
    total_orders: totalOrders,
    offset: 0,
    limit: orders.length || pageSize,
    generated_at: generatedAt,
    orders,
  };
}

export async function fetchScorecard(payload: ScorecardRequestPayload): Promise<ScorecardReport> {
  const response = await fetch(`${API_BASE_URL}/api/tca/scorecard`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as ScorecardReport;
}
// -- Regime distribution ------------------------------------------------------

export interface RegimeDistributionRow {
  date: string;
  market_code: string;
  low: number;
  normal: number;
  high: number;
  extreme: number;
  none: number;
  total: number;
}

export interface RegimeDistributionResponse {
  success: boolean;
  rows: RegimeDistributionRow[];
  regime_dim: string;
  config_version: string | null;
  start_date: string;
  end_date: string;
}

export async function fetchRegimeDistribution(params: {
  startDate: string; // YYYY-MM-DD
  endDate: string;   // YYYY-MM-DD
  regimeDim?: 'vol_regime' | 'liq_regime' | 'trend_regime';
}): Promise<RegimeDistributionResponse> {
  const url = new URL(
    `${API_BASE_URL}/api/costview/regime-distribution`,
    window.location.origin,
  );
  url.searchParams.set('start_date', params.startDate);
  url.searchParams.set('end_date', params.endDate);
  url.searchParams.set('regime_dim', params.regimeDim ?? 'vol_regime');
  const response = await fetch(url.toString().replace(window.location.origin, API_BASE_URL || ''), {
    method: 'GET',
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as RegimeDistributionResponse;
}