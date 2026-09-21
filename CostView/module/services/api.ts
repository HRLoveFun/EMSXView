import type {
  BdibHealthReport,
  EvaluationCompareRequest,
  EvaluationComparisonReport,
  Granularity,
  LastPreset,
  MetricCoverageReport,
  ScorecardReport,
  ScorecardRequestPayload,
  TcaAnalyzeRequest,
  TcaOrderAggregate,
  TcaReport,
  TcaReportSummary,
  ThresholdRule,
  UpdateStatusResponse,
} from '../types';

const API_BASE_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
const TOKEN_KEY = 'emsx_token';

// 010-extract-pipeline: 数据更新维护已迁独立项目 EMSXDataPipeline Runner。
// P2-4 整改：触发/状态查询不再直连 Runner（:8100），统一走 :3000 鉴权代理
// /api/tca/runner/*（后端 backend/api/routers/costview.py 转发）。

interface RunnerStatus {
  id: string;
  state: 'idle' | 'running' | 'success' | 'failed';
  started_at: number | null;
  finished_at: number | null;
  duration_sec: number | null;
  returncode: number | null;
  log_tail: string[];
}

function isoOrNull(epoch: number | null): string | null {
  return epoch === null ? null : new Date(epoch * 1000).toISOString();
}

function mapRunnerStatus(s: RunnerStatus): UpdateStatusResponse {
  const status: UpdateStatusResponse['status'] =
    s.state === 'running'
      ? 'running'
      : s.state === 'success'
        ? 'completed'
        : s.state === 'failed'
          ? 'failed'
          : 'completed';
  return {
    job_id: s.id,
    status,
    started_at: isoOrNull(s.started_at),
    completed_at: isoOrNull(s.finished_at),
    error:
      s.state === 'failed'
        ? `pipeline exited with code ${s.returncode ?? 'unknown'}`
        : null,
    stage: null,
    overall_progress: s.state === 'success' ? 1 : 0,
    last_activity_at: isoOrNull(s.finished_at ?? s.started_at),
  };
}

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
  // B4 整改：detail 支持结构化 {code, message}（503 数据新鲜度/降级语义），
  // 字符串 detail 向后兼容
  const d = body?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && d.message) {
    return `[${d.code ?? 'error'}] ${d.message}`;
  }
  return body?.error ?? `Request failed: ${response.status}`;
}

/** analyze 返回 202 时抛出：默认日期数据未生成，数据管道已自动触发 */
export class PipelineTriggeredError extends Error {
  readonly jobId: string;
  readonly targetDate: string;

  constructor(jobId: string, targetDate: string, message: string) {
    super(message);
    this.name = 'PipelineTriggeredError';
    this.jobId = jobId;
    this.targetDate = targetDate;
  }
}

export async function analyzeTca(request: TcaAnalyzeRequest): Promise<TcaReport> {
  const response = await fetch(`${API_BASE_URL}/api/tca/analyze`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(request),
  });

  // 202：默认日期数据未生成，后端已自动触发数据管道
  if (response.status === 202) {
    const json = await response.json();
    const data = json.data ?? {};
    throw new PipelineTriggeredError(
      data.job_id ?? '',
      data.target_date ?? '',
      json.message ?? '数据管道已触发',
    );
  }

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as TcaReport;
}

/** 003-tca-core-benchmarks: Order 级 TCA 聚合查询 */
export interface TcaOrderReport {
  filters: TcaAnalyzeRequest['filters'] & { aggregation: string; limit: number; offset: number };
  total_orders: number;
  offset: number;
  limit: number;
  generated_at: string;
  orders: TcaOrderAggregate[];
  /** P0 降级可见性：false 表示订单级聚合未启用（TCA_ORDER_AGG_ENABLED=0），
   *  orders 为空不代表无匹配数据；缺省视为 true（旧后端兼容） */
  order_agg_enabled?: boolean;
}

export async function analyzeTcaOrders(request: TcaAnalyzeRequest): Promise<TcaOrderReport> {
  const response = await fetch(`${API_BASE_URL}/api/tca/analyze-orders`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as TcaOrderReport;
}

export async function getUpdateStatus(_jobId: string): Promise<UpdateStatusResponse> {
  // Runner 为单任务模型，jobId 仅作前端一致性占位（下划线前缀表示有意不使用）；
  // 状态查询经 :3000 鉴权代理（后端解包 ApiResponse.data 后按原映射转换）
  const response = await fetch(`${API_BASE_URL}/api/tca/runner/status`, {
    headers: getAuthHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const json = await response.json();
  return mapRunnerStatus(json.data as RunnerStatus);
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

/** 026 阶段三：评估层可比性比较（POST /api/tca/evaluation/compare）。
 *
 *  三条约束都在**服务端**执行，前端只做呈现、不承担约束责任：
 *  1. 可比性判定在服务端 —— 不可比时 `comparisons` 为空数组，后端不返回数值；
 *  2. `benchmark` 必填（D1 基准冻结），缺失即 422；
 *  3. 每对比较同时返回未校正与校正后的 p 值。
 */
export async function fetchEvaluationComparison(
  payload: EvaluationCompareRequest,
): Promise<EvaluationComparisonReport> {
  const response = await fetch(`${API_BASE_URL}/api/tca/evaluation/compare`, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const json = await response.json();
  return json.data as EvaluationComparisonReport;
}

// -- Monitoring（BDIB 健康 / 指标覆盖率 / 报告聚合）----------------------------

/** 监控查询公共参数：last 预设与 start/end 显式区间二选一（YYYYMMDD） */
interface MonitoringQuery {
  last?: LastPreset;
  startDate?: string;
  endDate?: string;
}

/** 组装监控端点查询串（时间范围互斥：显式区间优先忽略 last 由调用方保证） */
function buildMonitoringUrl(path: string, query: MonitoringQuery, extra?: Record<string, string>): string {
  const params = new URLSearchParams();
  if (query.startDate && query.endDate) {
    params.set('start_date', query.startDate);
    params.set('end_date', query.endDate);
  } else if (query.last) {
    params.set('last', query.last);
  }
  for (const [key, value] of Object.entries(extra ?? {})) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  return `${API_BASE_URL}${path}${qs ? `?${qs}` : ''}`;
}

/** GET JSON 并解包 {success, data, message} 响应 */
async function fetchMonitoringJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: getAuthHeaders() });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const json = await response.json();
  return json.data as T;
}

export async function fetchBdibHealth(query: MonitoringQuery): Promise<BdibHealthReport> {
  return fetchMonitoringJson<BdibHealthReport>(
    buildMonitoringUrl('/api/tca/monitoring/bdib-health', query),
  );
}

export async function fetchMetricCoverage(
  query: MonitoringQuery,
  metrics?: string[],
  groupByExchange = false,
  granularity?: Granularity,
): Promise<MetricCoverageReport> {
  const extra: Record<string, string> = {};
  if (metrics?.length) extra.metrics = metrics.join(',');
  if (groupByExchange) extra.group_by_exchange = 'true';
  if (granularity) extra.granularity = granularity;
  return fetchMonitoringJson<MetricCoverageReport>(
    buildMonitoringUrl('/api/tca/monitoring/metric-coverage', query, extra),
  );
}

interface ReportSummaryQuery extends MonitoringQuery {
  broker?: string | string[];
  algo?: string | string[];
  symbol?: string | string[];
  exchange?: string | string[];
  metrics?: string[];
  /** 008: 异常路由判定阈值覆盖（与后端 ThresholdRules 契约对齐，页面明细与导出 HTML 同源） */
  thresholds?: Record<string, ExportHtmlThresholdPayload>;
  minFillCount?: number;
  minNotionalUsd?: number;
  /** 026: 聚合粒度（day/week/month；不传则由后端按 day 取默认） */
  granularity?: Granularity;
}

/** 将单值/数组筛选参数序列化为逗号分隔串 */
function joinFilter(value: string | string[] | undefined): string | undefined {
  if (!value) return undefined;
  if (Array.isArray(value)) return value.filter(Boolean).join(',') || undefined;
  return value;
}

export async function fetchTcaReportSummary(query: ReportSummaryQuery): Promise<TcaReportSummary> {
  const extra: Record<string, string> = {};
  const broker = joinFilter(query.broker);
  const algo = joinFilter(query.algo);
  const symbol = joinFilter(query.symbol);
  const exchange = joinFilter(query.exchange);
  if (broker) extra.broker = broker;
  if (algo) extra.algo = algo;
  if (symbol) extra.symbol = symbol;
  if (exchange) extra.exchange = exchange;
  if (query.metrics?.length) extra.metrics = query.metrics.join(',');
  if (query.minFillCount != null) extra.min_fill_count = String(query.minFillCount);
  if (query.minNotionalUsd != null) extra.min_notional_usd = String(query.minNotionalUsd);
  if (query.granularity) extra.granularity = query.granularity;
  // 008: 阈值覆盖随查询下发（JSON 串，与 export-html 端点同契约）
  if (query.thresholds && Object.keys(query.thresholds).length) {
    extra.thresholds = JSON.stringify(query.thresholds);
  }
  return fetchMonitoringJson<TcaReportSummary>(
    buildMonitoringUrl('/api/tca/monitoring/report-summary', query, extra),
  );
}

/** 006/014: 阈值规则 → 导出端点 thresholds 查询参数（与后端 ThresholdRules 契约对齐）。
 *  双档（ADR-0018）：warning 决定是否入清单，critical 仅用于分级标注。
 *  mode 直接复用 ThresholdRule 的联合类型，避免模式枚举在多处各写一份。 */
export interface ExportHtmlThresholdPayload {
  mode: ThresholdRule['mode'];
  warning: number;
  critical: number;
  enabled: boolean;
}

/** 异常路由判定默认阈值（后端 anomaly-thresholds 端点返回） */
interface AnomalyThresholdsResponse {
  rules: Record<string, ExportHtmlThresholdPayload>;
  rule_meta: Record<string, { label: string; metric_field: string; scale: number }>;
}

/** 008: 拉取后端异常路由判定默认阈值（后端为唯一真相源，前端 Reset/首装从此取） */
export async function fetchAnomalyThresholds(): Promise<AnomalyThresholdsResponse> {
  return fetchMonitoringJson<AnomalyThresholdsResponse>(
    buildMonitoringUrl('/api/tca/monitoring/anomaly-thresholds', {}),
  );
}

interface ExportHtmlQuery extends MonitoringQuery {
  broker?: string | string[];
  algo?: string | string[];
  symbol?: string | string[];
  exchange?: string | string[];
  thresholds?: Record<string, ExportHtmlThresholdPayload>;
  minFillCount?: number;
  minNotionalUsd?: number;
  /** 026: 聚合粒度（与页面视图同参数，导出报告与页面口径一致） */
  granularity?: Granularity;
}

/** 006: 一键导出 HTML 报告（附件下载）。返回下载文件名。 */
export async function fetchExportHtml(query: ExportHtmlQuery): Promise<string> {
  const params = new URLSearchParams();
  if (query.startDate && query.endDate) {
    params.set('start_date', query.startDate);
    params.set('end_date', query.endDate);
  } else if (query.last) {
    params.set('last', query.last);
  }
  for (const [key, value] of Object.entries({
    broker: joinFilter(query.broker), algo: joinFilter(query.algo),
    symbol: joinFilter(query.symbol), exchange: joinFilter(query.exchange),
  })) {
    if (value) params.set(key, value);
  }
  if (query.thresholds && Object.keys(query.thresholds).length) {
    params.set('thresholds', JSON.stringify(query.thresholds));
  }
  if (query.minFillCount != null) {
    params.set('min_fill_count', String(query.minFillCount));
  }
  if (query.minNotionalUsd != null) {
    params.set('min_notional_usd', String(query.minNotionalUsd));
  }
  if (query.granularity) {
    params.set('granularity', query.granularity);
  }

  const response = await fetch(
    `${API_BASE_URL}/api/tca/monitoring/export-html?${params.toString()}`,
    { headers: getAuthHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const fileName = match?.[1] ?? `tca_report_${new Date().toISOString().slice(0, 10)}.html`;

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
  return fileName;
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

interface RegimeDistributionResponse {
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
