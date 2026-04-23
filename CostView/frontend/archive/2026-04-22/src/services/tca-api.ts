/**
 * TCA API service — typed wrappers for CostView TCA endpoints.
 *
 * All requests go through the same API base URL as the rest of the
 * Execution frontend (VITE_API_URL or Vite dev-server proxy).
 *
 * Data constraint: the backend ONLY reads from fill/bdib SQLite databases;
 * no external API calls are made.
 */

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';

const TOKEN_KEY = 'emsx_token';

function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  return headers;
}

// ── Domain types ─────────────────────────────────────────────────────────────

export interface TcaFilterPayload {
  order_ids?: string[];
  algo?: string;
  start_date?: string;   // YYYYMMDD
  end_date?: string;     // YYYYMMDD
  broker?: string;
  symbol?: string;
}

export interface TcaAnalyzeRequest {
  filters: TcaFilterPayload;
  aggregation?: 'per_order' | 'aggregated';
  limit?: number;
  offset?: number;
}

export interface TcaTimeSeriesPoint {
  ts: string;
  close: number | null;
  fill_px: number | null;
  fill_volume: number | null;
  volume: number | null;
  cum_volume_pct: number | null;
  cum_fill_vwap: number | null;
  cum_vwap: number | null;
  cum_tracking_error: number | null;
}

export interface TcaRouteDetail {
  order_id: string;
  route_id: string;
  order_as_of_date: string;
  broker: string | null;
  side: string | null;
  start_time: string | null;
  end_time: string | null;
  fill_pct: number | null;
  exec_price: number | null;
  interval_vwap: number | null;
  tracking_error_bps: number | null;
  volume_pct_interval: number | null;
  time_series: TcaTimeSeriesPoint[];
}

export interface TcaOrderSummary {
  order_id: string;
  order_as_of_date: string;
  equ_ticker: string | null;
  side: string | null;
  algo: string | null;
  start_time: string | null;
  end_time: string | null;
  fill_pct: number | null;
  exec_price: number | null;
  interval_vwap: number | null;
  tracking_error_bps: number | null;
  volume_pct_interval: number | null;
  volume_pct_adv5: number | null;
  volume_pct_adv20: number | null;
  intraday_volatility: number | null;
  price_movement_pct: number | null;
  data_quality_warning: boolean;
  routes: TcaRouteDetail[];
}

export interface TcaReport {
  filters: TcaFilterPayload & { aggregation: string; limit: number; offset: number };
  total_orders: number;
  offset: number;
  limit: number;
  generated_at: string;
  orders: TcaOrderSummary[];
}

export interface TriggerUpdateResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface UpdateStatusResponse {
  job_id: string;
  status: 'started' | 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

// ── API calls ─────────────────────────────────────────────────────────────────

/**
 * Run TCA analysis with the given filters.
 * Returns the structured TcaReport, or throws on error.
 */
export async function analyzeTca(req: TcaAnalyzeRequest): Promise<TcaReport> {
  const url = `${API_BASE_URL}/api/tca/analyze`;
  const response = await fetch(url, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `TCA analyze failed: ${response.status}`);
  }

  const json = await response.json();
  return json.data as TcaReport;
}

/**
 * Trigger the daily update pipeline manually.
 * Returns a job_id for status polling.
 */
export async function triggerUpdate(): Promise<TriggerUpdateResponse> {
  const url = `${API_BASE_URL}/api/tca/trigger-update`;
  const response = await fetch(url, {
    method: 'POST',
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Trigger failed: ${response.status}`);
  }

  return response.json() as Promise<TriggerUpdateResponse>;
}

/**
 * Poll the status of a triggered pipeline job.
 */
export async function getUpdateStatus(jobId: string): Promise<UpdateStatusResponse> {
  const url = `${API_BASE_URL}/api/tca/update-status/${encodeURIComponent(jobId)}`;
  const response = await fetch(url, { headers: getAuthHeaders() });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body?.detail ?? `Status check failed: ${response.status}`);
  }

  return response.json() as Promise<UpdateStatusResponse>;
}
