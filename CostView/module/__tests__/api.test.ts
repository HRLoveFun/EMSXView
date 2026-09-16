import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyzeTca, PipelineTriggeredError } from '../services/api';

// 全局 fetch mock
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

afterEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

/** 构造 Response 对象 */
const jsonResponse = (status: number, body: unknown): Response =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

describe('analyzeTca', () => {
  it('200 返回报告数据', async () => {
    const report = { total_orders: 2, orders: [], filters: {} };
    mockFetch.mockResolvedValue(jsonResponse(200, { success: true, data: report }));

    const result = await analyzeTca({ filters: {}, limit: 5 });
    expect(result.total_orders).toBe(2);
  });

  it('202 抛 PipelineTriggeredError 并携带 job_id/target_date', async () => {
    mockFetch.mockResolvedValue(jsonResponse(202, {
      success: false,
      data: { pipeline_triggered: true, job_id: 'job-abc', target_date: '20260804', status: 'started' },
      message: '20260804 数据尚未生成，已自动触发数据管道',
    }));

    const error = await analyzeTca({ filters: {}, limit: 5 }).catch((e) => e);
    expect(error).toBeInstanceOf(PipelineTriggeredError);
    expect(error.jobId).toBe('job-abc');
    expect(error.targetDate).toBe('20260804');
    expect(error.message).toContain('已自动触发数据管道');
  });

  it('503 抛普通 Error（detail 文案）', async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, { detail: 'tca_route_summary is empty' }));

    await expect(analyzeTca({ filters: {}, limit: 5 })).rejects.toThrow('tca_route_summary is empty');
  });
});
