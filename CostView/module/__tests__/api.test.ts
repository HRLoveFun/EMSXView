import { afterEach, describe, expect, it, vi } from 'vitest';
import { analyzeTca, exportTraderCsv } from '../services/api';

// 全局 fetch mock
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);
// jsdom 无 createObjectURL；下载实现需要它（只验证文件名/URL，不落盘）
Object.defineProperty(URL, 'createObjectURL', {
  configurable: true, value: vi.fn(() => 'blob:mock'),
});
Object.defineProperty(URL, 'revokeObjectURL', {
  configurable: true, value: vi.fn(),
});

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

  it('零匹配 200 空报告正常返回（空结果不再当异常）', async () => {
    mockFetch.mockResolvedValue(jsonResponse(200, {
      success: true,
      data: { total_orders: 0, orders: [], filters: {} },
      message: '该筛选条件下无匹配路由',
    }));

    const result = await analyzeTca({ filters: { broker: 'NOSUCH' }, limit: 5 });
    expect(result.total_orders).toBe(0);
  });

  it('503 结构化 error（合并模式 ApiResponse 信封）渲染为 [code] message', async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, {
      success: false,
      error: { code: 'data_not_ready', message: '20260921 数据尚未生成' },
    }));

    await expect(analyzeTca({ filters: {}, limit: 5 }))
      .rejects.toThrow('[data_not_ready] 20260921 数据尚未生成');
  });

  it('503 字符串 error 原样展示（不再被兜底文案吞掉）', async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, {
      success: false,
      error: '[query_timeout] 查询超时 (>120s)，请缩小时间范围或稍后重试',
    }));

    await expect(analyzeTca({ filters: {}, limit: 5 }))
      .rejects.toThrow('[query_timeout] 查询超时 (>120s)');
  });

  it('standalone :8002 的 detail 形态同样支持结构化降级', async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, {
      detail: { code: 'data_source_unavailable', message: 'CostView database not found' },
    }));

    await expect(analyzeTca({ filters: {}, limit: 5 }))
      .rejects.toThrow('[data_source_unavailable] CostView database not found');
  });

  it('无法解析的载荷回落到状态码文案', async () => {
    mockFetch.mockResolvedValue(jsonResponse(422, {
      detail: [{ loc: ['body', 'filters'], msg: 'invalid' }],
    }));

    await expect(analyzeTca({ filters: {}, limit: 5 })).rejects.toThrow('Request failed: 422');
  });

  it('503 字符串 detail（standalone 形态）原样展示', async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, { detail: 'tca_route_summary is empty' }));

    await expect(analyzeTca({ filters: {}, limit: 5 })).rejects.toThrow('tca_route_summary is empty');
  });
});

describe('exportTraderCsv', () => {
  it('URL 携带 kind/筛选，剥离分页；返回 Content-Disposition 文件名', async () => {
    mockFetch.mockResolvedValue(new Response('# spec_version=2026.11.04\n', {
      status: 200,
      headers: {
        'Content-Disposition':
          'attachment; filename="trader_orders_20261020_20261022_abcd1234.csv"',
      },
    }));

    const name = await exportTraderCsv('orders', {
      startDate: '20261020', endDate: '20261022',
      trader: ['HRCHEN'], quality: 'all', limit: 50, offset: 50,
    });

    expect(name).toBe('trader_orders_20261020_20261022_abcd1234.csv');
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('/api/tca/trader/export?');
    expect(url).toContain('kind=orders');
    expect(url).toContain('start_date=20261020');
    expect(url).toContain('trader=HRCHEN');
    expect(url).not.toContain('limit=');
    expect(url).not.toContain('offset=');
    expect(url).not.toContain('quality=');      // quality=all 不发（与列表一致）
  });

  it('order_id 随导出单笔请求下发', async () => {
    mockFetch.mockResolvedValue(new Response('csv', { status: 200 }));

    await exportTraderCsv('fills', {}, '5292736');

    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('kind=fills');
    expect(url).toContain('order_id=5292736');
  });

  it('422 上限错误透传后端文案', async () => {
    mockFetch.mockResolvedValue(jsonResponse(422, {
      detail: '导出订单数 60,000 超过上限 50,000，请缩小日期范围或加筛选条件',
    }));

    await expect(exportTraderCsv('orders', {}))
      .rejects.toThrow('超过上限 50,000');
  });
});
