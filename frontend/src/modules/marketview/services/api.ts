import type { MarketSnapshotPayload, MarketSnapshotRequest } from '../types';
import type { IntradayFeatureRequest, IntradayFeatureSnapshot } from '../types';

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