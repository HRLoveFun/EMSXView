/**
 * 运行时 API/handoff 响应校验 (M2)。
 *
 * 用 zod 定义跨模块契约 schema, 在 service 层替换纯类型断言 (`as Xxx`)。
 * 后端 Pydantic 契约变更时, 前端在校验点立即显式报错, 而非静默漂移。
 *
 * 用法:
 *     const handoff = parseApiData(marketToExecutionHandoffSchema, body);
 */

import { z } from 'zod';

// ─── Handoff 契约 (WBS-08, 与 backend/api/schemas/handoff.py 对齐) ─────────

export const handoffMetadataSchema = z.object({
  contract_version: z.string(),
  source: z.string(),
  handoff_target: z.string(),
  generated_at: z.string(),
  trace_id: z.string(),
  origin_trace_id: z.string().nullable().optional(),
});

export const candidateRowSchema = z.object({
  equ_ticker: z.string(),
  trade_date: z.string(),
  daily_close: z.number().nullable(),
  total_volume: z.number().nullable(),
  adv_20d: z.number().nullable(),
  daily_volatility: z.number().nullable(),
  intraday_volatility: z.number().nullable(),
  liquidity_alert: z.string(),
  volatility_alert: z.string(),
});

export const candidatePayloadSchema = z.object({
  source: z.string(),
  handoff_target: z.string(),
  trade_date: z.string().nullable(),
  pool_id: z.string(),
  pool_label: z.string().nullable(),
  row_count: z.number(),
  candidates: z.array(candidateRowSchema),
});

export const marketToExecutionHandoffSchema = z.object({
  metadata: handoffMetadataSchema,
  trade_date: z.string().nullable(),
  pool_id: z.string(),
  pool_label: z.string().nullable(),
  candidate_payload: candidatePayloadSchema,
  execution_hint: z.record(z.string(), z.unknown()),
});

export const brokerRecommendationSchema = z.object({
  metadata: handoffMetadataSchema,
  cohort: z.string(),
  asset_class: z.string().nullable(),
  broker: z.string().nullable(),
  strategy: z.string().nullable(),
  urgency: z.string().nullable(),
  sample_size: z.number(),
  arrival_bps: z.number().nullable(),
  implementation_bps: z.number().nullable(),
  severity: z.string(),
  rationale: z.string(),
  source_report_trace_id: z.string().nullable(),
});

// ─── 解析辅助 ────────────────────────────────────────────────────────────────

/**
 * 从统一响应体 `{ success, data, message }` 中提取 data 字段并做运行时校验。
 * 校验失败抛带上下文的 Error — 契约漂移显式化, 不再静默信任后端。
 */
export function parseApiData<TSchema extends z.ZodType>(
  schema: TSchema,
  body: unknown,
  context: string,
): z.output<TSchema> {
  const candidate = (body as { data?: unknown } | null)?.data ?? body;
  const result = schema.safeParse(candidate);
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `${i.path.join('.')}: ${i.message}`)
      .join('; ');
    throw new Error(`API 响应契约校验失败 [${context}]: ${issues}`);
  }
  return result.data;
}

/** 可空变体 — data 为 null 时返回 null (契约允许空数据)。 */
export function parseApiDataNullable<TSchema extends z.ZodType>(
  schema: TSchema,
  body: unknown,
  context: string,
): z.output<TSchema> | null {
  const candidate = (body as { data?: unknown } | null)?.data ?? body;
  if (candidate == null) return null;
  return parseApiData(schema, { data: candidate }, context);
}
