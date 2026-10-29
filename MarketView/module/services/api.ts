import type { MarketSnapshotPayload, MarketSnapshotRequest } from '../types';
import type { IntradayFeatureRequest, IntradayFeatureSnapshot } from '../types';
import type { PreTradeOrdersPayload } from '../types';
import type { MarketStateSnapshot, PreTradeBoardPayload } from '../types';
import type { PoolBoardPayload } from '../types';
import type { MonitorBoardPayload, TickerDetailPayload } from '../types';

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

// 网关类状态：Vite dev 代理（或生产 Nginx）在上游不可达时返回这些码
const GATEWAY_STATUS = new Set([500, 502, 503, 504]);
// 代理转发失败的典型文本（Vite/http-proxy 的错误的响应体）
const PROXY_FAILURE_HINT = /ECONNREFUSED|ECONNRESET|proxy error|socket hang up/i;

/**
 * 把响应体转成可读错误。
 *
 * 不能把「500 + 非 JSON」一律当服务端异常：MarketView 微服务（:8001）未启动时，
 * 代理返回 500 且 body 为空/含 ECONNREFUSED，旧实现会渲染成
 * `Request failed: 500`（用户无法判断该做什么）。这里对这类情形给出启动指引，
 * 而真正的 500（如 `Internal Server Error` 文本）仍原样透出。
 */
async function readError(response: Response): Promise<string> {
  const text = await response.text();
  let detail: string | undefined;
  try {
    const body = JSON.parse(text) as { detail?: string; error?: string } | null;
    detail = body?.detail ?? body?.error;
  } catch {
    detail = undefined;
  }
  if (detail) return detail;
  if (GATEWAY_STATUS.has(response.status) && (!text.trim() || PROXY_FAILURE_HINT.test(text))) {
    return 'MarketView service unavailable — start it with "python MarketView/main.py" (or emsxview.bat start)';
  }
  return text || `Request failed: ${response.status}`;
}

const DEFAULT_MARKET_SNAPSHOT_REQUEST: Required<
  Pick<
    MarketSnapshotRequest,
    'limit' | 'pool_id' | 'sort_by' | 'sort_direction' | 'liquidity_alert' | 'volatility_alert'
  >
> = {
  limit: 40,
  pool_id: 'all',
  sort_by: 'total_volume',
  sort_direction: 'desc',
  liquidity_alert: 'all',
  volatility_alert: 'all',
};

function appendNumberParam(params: URLSearchParams, key: string, value: number | undefined): void {
  if (value == null || !Number.isFinite(value)) {
    return;
  }
  params.set(key, String(value));
}

export async function fetchMarketSnapshot(request: MarketSnapshotRequest = {}): Promise<MarketSnapshotPayload> {
  const normalized = {
    ...DEFAULT_MARKET_SNAPSHOT_REQUEST,
    ...request,
  };

  const params = new URLSearchParams({
    limit: String(normalized.limit),
    pool_id: normalized.pool_id,
    liquidity_alert: normalized.liquidity_alert,
    volatility_alert: normalized.volatility_alert,
    sort_by: normalized.sort_by,
    sort_direction: normalized.sort_direction,
  });

  if (normalized.trade_date) {
    params.set('trade_date', normalized.trade_date);
  }

  appendNumberParam(params, 'min_adv_20d', normalized.min_adv_20d);
  appendNumberParam(params, 'min_total_volume', normalized.min_total_volume);
  appendNumberParam(params, 'min_daily_volatility', normalized.min_daily_volatility);
  appendNumberParam(params, 'min_intraday_volatility', normalized.min_intraday_volatility);

  const response = await fetch(`${API_BASE_URL}/api/marketview/snapshot?${params.toString()}`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as MarketSnapshotPayload;
}

export async function fetchIntradayFeatures(
  request: IntradayFeatureRequest,
): Promise<IntradayFeatureSnapshot> {
  if (!request.tickers.length) {
    throw new Error('At least one ticker is required for intraday features');
  }

  const params = new URLSearchParams({
    tickers: request.tickers.join(','),
    bucket_minutes: String(request.bucket_minutes ?? 30),
  });
  if (request.trade_date) {
    params.set('trade_date', request.trade_date);
  }

  const response = await fetch(
    `${API_BASE_URL}/api/marketview/intraday-features?${params.toString()}`,
    { headers: getAuthHeaders() },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as IntradayFeatureSnapshot;
}

// EMSX 导出盘前单（057 DL-01）：只读收件箱最新一份导出，无查询参数
export async function fetchPreTradeOrders(): Promise<PreTradeOrdersPayload> {
  const response = await fetch(`${API_BASE_URL}/api/marketview/pre-trade-orders`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as PreTradeOrdersPayload;
}

// 057 DL-14：盘前单装配（四路产物汇总），只读
export async function fetchPreTradeBoard(): Promise<PreTradeBoardPayload> {
  const response = await fetch(`${API_BASE_URL}/api/marketview/pretrade-board`, {
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as PreTradeBoardPayload;
}

// 057 DL-15：盘中市场状态快照（实时列数据源；开关关闭时 enabled=false）
export async function fetchMarketStateSnapshot(
  tickers?: string[],
): Promise<MarketStateSnapshot> {
  const params = new URLSearchParams();
  if (tickers?.length) {
    params.set('tickers', tickers.join(','));
  }
  const query = params.toString();
  const response = await fetch(
    `${API_BASE_URL}/api/market-state/snapshot${query ? `?${query}` : ''}`,
    { headers: getAuthHeaders() },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as MarketStateSnapshot;
}

/**
 * 盘中市场状态 WebSocket 地址（core 后端 `/ws/market-state`）。
 *
 * `VITE_API_URL` 为空时走同源（dev server 的 `/ws` 代理）；配置为 http(s) 绝对
 * 地址时同端口换成 ws(s)。tickers 作为连接期白名单，切换股票池时由调用方重连。
 */
export function resolveMarketStateStreamUrl(tickers: string[] = []): string {
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
  const origin = base
    ? base.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`;
  const params = new URLSearchParams();
  if (tickers.length) {
    params.set('tickers', tickers.join(','));
  }
  const query = params.toString();
  return `${origin}/ws/market-state${query ? `?${query}` : ''}`;
}

// 057 DL-29：固定筛选池池板（量价 / 难度 / 成本同屏，只读）
export async function fetchPoolBoard(
  poolId: string,
  tradeDate?: string,
  limit = 40,
): Promise<PoolBoardPayload> {
  const params = new URLSearchParams({ pool_id: poolId, limit: String(limit) });
  if (tradeDate) {
    params.set('trade_date', tradeDate);
  }
  const response = await fetch(
    `${API_BASE_URL}/api/marketview/pool-board?${params.toString()}`,
    { headers: getAuthHeaders() },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as PoolBoardPayload;
}

// ── 057 节点一：监控台（高亮面板 + 监控表 + 行详情）─────────────────────

export async function fetchMonitorBoard(
  poolId?: string,
  tradeDate?: string,
): Promise<MonitorBoardPayload> {
  const params = new URLSearchParams();
  if (poolId) params.set('pool_id', poolId);
  if (tradeDate) params.set('trade_date', tradeDate);
  const query = params.toString();
  const response = await fetch(
    `${API_BASE_URL}/api/marketview/monitor-board${query ? `?${query}` : ''}`,
    { headers: getAuthHeaders() },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as MonitorBoardPayload;
}

export async function fetchTickerDetail(
  ticker: string,
  tradeDate?: string,
): Promise<TickerDetailPayload> {
  const params = new URLSearchParams({ ticker });
  if (tradeDate) params.set('trade_date', tradeDate);
  const response = await fetch(
    `${API_BASE_URL}/api/marketview/ticker-detail?${params.toString()}`,
    { headers: getAuthHeaders() },
  );

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as TickerDetailPayload;
}

// 057 DL-29 增强：向 core 注册池内标的 mktdata 订阅（实时价）
export interface SubscribeResult {
  accepted: string[];
  rejected: number;
  total_extra: number;
}

// ── 参考数据：中文简称（core 的 refdata 端点，进程内缓存）──────────────────
export interface SecurityNamesPayload {
  names: Record<string, string>;
  missing: string[];
  field: string;
}

/** 名称口径固定为英文短名（SHORT_NAME） */
export async function fetchSecurityNames(tickers: string[]): Promise<SecurityNamesPayload> {
  const params = new URLSearchParams({ tickers: tickers.join(',') });
  const response = await fetch(`${API_BASE_URL}/api/securities/names?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const body = (await response.json()) as { data: SecurityNamesPayload };
  return body.data;
}

export async function subscribeMarketState(tickers: string[]): Promise<SubscribeResult> {
  const response = await fetch(`${API_BASE_URL}/api/market-state/subscribe`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ tickers }),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as SubscribeResult;
}