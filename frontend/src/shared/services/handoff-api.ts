/**
 * WBS-08 handoff contract API client.
 *
 * Three cross-module contracts backed by `platform_data.HandoffExchangeAdapter`:
 *   1. MarketView → ExecutionView   publishMarketCandidates / fetchActiveCandidateHandoff
 *   2. ExecutionView → CostView     publishPostTradeHandoff
 *   3. CostView → ExecutionView     pinBrokerRecommendation / fetchBrokerRecommendations
 *
 * 防护 (M2): 所有响应经 zod 运行时校验 (shared/lib/api-schema.ts),
 * 替换纯类型断言 — 后端契约变更时前端立即显式报错。
 */

import {
  parseApiData,
  parseApiDataNullable,
  marketToExecutionHandoffSchema,
  brokerRecommendationSchema,
} from '@shared/lib/api-schema';

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
  // B4 整改：detail 支持结构化 {code, message}，字符串 detail 向后兼容
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) {
    return `[${d.code ?? 'error'}] ${d.message}`;
  }
  return body?.error ?? body?.message ?? `Request failed: ${response.status}`;
}

// ─── Contract types ──────────────────────────────────────────────────────────

interface HandoffMetadata {
  contract_version: string;
  source: string;
  handoff_target: string;
  generated_at: string;
  trace_id: string;
  origin_trace_id?: string | null;
  /** 发布方模块成熟度；缺省/未知时消费方不得默认信任 */
  source_maturity?: 'GA' | 'Beta' | 'Scaffold' | null;
}

interface CandidateRow {
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

interface CandidatePayload {
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
  return parseApiData(marketToExecutionHandoffSchema, body, 'publishMarketCandidates');
}

export async function fetchActiveCandidateHandoff(): Promise<MarketToExecutionHandoff | null> {
  const response = await fetch(`${API_BASE_URL}/api/executions/handoff/candidates`, {
    method: 'GET',
    headers: authHeaders(),
  });
  if (!response.ok) throw new Error(await readError(response));
  const body = await response.json();
  return parseApiDataNullable(marketToExecutionHandoffSchema, body, 'fetchActiveCandidateHandoff');
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
  // P3 整改（A6）：发送前字节级预检，与后端契约 HANDOFF_MAX_STRATEGY_PARAMS_BYTES
  // (64KB) 对齐——数值由契约测试跨层锁定，禁止单侧调整。
  const MAX_STRATEGY_PARAMS_BYTES = 64 * 1024;
  const paramsBytes = new TextEncoder().encode(
    JSON.stringify(req.strategy_params ?? {}),
  ).length;
  if (paramsBytes > MAX_STRATEGY_PARAMS_BYTES) {
    throw new Error(
      `strategy_params 超限: ${paramsBytes} bytes (max ${MAX_STRATEGY_PARAMS_BYTES})，请精简后再发布`,
    );
  }
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
  return parseApiData(
    brokerRecommendationSchema.array(),
    { data: recs },
    'fetchBrokerRecommendations',
  );
}
