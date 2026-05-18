/**
 * WBS-08 handoff contract API client.
 *
 * Three cross-module contracts backed by `platform_data.HandoffExchangeAdapter`:
 *   1. MarketView → ExecutionView   publishMarketCandidates / fetchActiveCandidateHandoff
 *   2. ExecutionView → CostView     publishPostTradeHandoff
 *   3. CostView → ExecutionView     pinBrokerRecommendation / fetchBrokerRecommendations
 */

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
const TOKEN_KEY = 'emsx_token';

function authHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    (headers as Record<string, string>).Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function readError(response: Response): Promise<string> {
  const body = await response.json().catch(() => ({}));
  return body?.detail ?? body?.error ?? body?.message ?? `Request failed: ${response.status}`;
}

// ─── Contract types ──────────────────────────────────────────────────────────

export interface HandoffMetadata {
  contract_version: string;
  source: string;
  handoff_target: string;
  generated_at: string;
  trace_id: string;
  origin_trace_id?: string | null;
}

export interface CandidateRow {
  equ_ticker: string;
  trade_date: string;
  daily_close: number | null;
  total_volume: number | null;
  adv_20d: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  liquidity_alert: string;
  volatility_alert: string;
}

export interface CandidatePayload {
  source: string;
  handoff_target: string;
  trade_date: string | null;
  pool_id: string;
  pool_label: string | null;
  row_count: number;
  candidates: CandidateRow[];
}

export interface MarketToExecutionHandoff {
  metadata: HandoffMetadata;
  trade_date: string | null;
  pool_id: string;
  pool_label: string | null;
  candidate_payload: CandidatePayload;
  execution_hint: Record<string, unknown>;
}

export interface BrokerRecommendation {
  metadata: HandoffMetadata;
  cohort: string;
  asset_class: string | null;
  broker: string | null;
  strategy: string | null;
  urgency: string | null;
  sample_size: number;
  arrival_bps: number | null;
  implementation_bps: number | null;
  severity: string;
  rationale: string;
  source_report_trace_id: string | null;
}

// ─── Contract 1: MarketView → ExecutionView ──────────────────────────────────

export interface PublishMarketCandidatesRequest {
  pool_id?: string;
  tickers?: string[];
  execution_hint?: Record<string, unknown>;
}

export async function publishMarketCandidates(
  req: PublishMarketCandidatesRequest,
): Promise<MarketToExecutionHandoff> {
  const response = await fetch(`${API_BASE_URL}/api/marketview/handoff/execution`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(req),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = await response.json();
  return (body?.data ?? body) as MarketToExecutionHandoff;
}

export async function fetchActiveCandidateHandoff(): Promise<MarketToExecutionHandoff | null> {
  const response = await fetch(`${API_BASE_URL}/api/executions/handoff/candidates`, {
    method: 'GET',
    headers: authHeaders(),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = await response.json();
  return (body?.data ?? null) as MarketToExecutionHandoff | null;
}

// ─── Contract 2: ExecutionView → CostView ────────────────────────────────────

export interface PublishPostTradeRequest {
  order_id: string;
  parent_execution_id?: string;
  broker?: string;
  strategy?: string;
  asset_class?: string;
  urgency?: string;
  route_ids?: string[];
  strategy_params?: Record<string, unknown>;
  candidate_trace_id?: string;
}

export async function publishPostTradeHandoff(req: PublishPostTradeRequest): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}/api/executions/handoff/post-trade`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(req),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

// ─── Contract 3: CostView → ExecutionView ────────────────────────────────────

export interface PinRecommendationRequest {
  cohort: string;
  asset_class?: string;
  broker?: string;
  strategy?: string;
  urgency?: string;
  sample_size: number;
  arrival_bps?: number | null;
  implementation_bps?: number | null;
  severity?: string;
  rationale?: string;
  source_report_trace_id?: string;
}

export async function pinBrokerRecommendation(req: PinRecommendationRequest): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}/api/tca/recommendations/pin`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(req),
  });
  if (!response.ok) throw new Error(await readError(response));
  return response.json();
}

export async function fetchBrokerRecommendations(
  params: { asset_class?: string; broker?: string; limit?: number } = {},
): Promise<BrokerRecommendation[]> {
  const q = new URLSearchParams();
  if (params.asset_class) q.set('assetClass', params.asset_class);
  if (params.broker) q.set('broker', params.broker);
  if (params.limit != null) q.set('limit', String(params.limit));
  const suffix = q.toString() ? `?${q.toString()}` : '';
  const response = await fetch(`${API_BASE_URL}/api/broker-recommendations${suffix}`, {
    method: 'GET',
    headers: authHeaders(),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = await response.json();
  const recs = body?.data?.recommendations ?? [];
  return recs as BrokerRecommendation[];
}