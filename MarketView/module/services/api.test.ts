import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchMarketSnapshot, fetchPoolBoard } from './api';

/** 用给定的 Response 替身拦截所有 fetch。 */
const stubFetchResponse = (response: Response): void => {
  vi.stubGlobal('fetch', vi.fn(async () => response));
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('MarketView api error mapping', () => {
  it('把「500 + 空体」识别为服务未启动，并给出启动指引', async () => {
    // Vite 代理在上游不可达时的真实形态：500、空体、非 JSON
    stubFetchResponse(new Response('', { status: 500 }));

    await expect(fetchMarketSnapshot()).rejects.toThrow(/MarketView service unavailable/);
  });

  it('把含 ECONNREFUSED 的代理错误体也识别为服务未启动', async () => {
    stubFetchResponse(
      new Response('Error: connect ECONNREFUSED 127.0.0.1:8001', { status: 500 }),
    );

    await expect(fetchPoolBoard('all')).rejects.toThrow(/MarketView service unavailable/);
  });

  it('真正的 500 文本原样透出，不误判为服务未启动', async () => {
    stubFetchResponse(new Response('Internal Server Error', { status: 500 }));

    await expect(fetchMarketSnapshot()).rejects.toThrow('Internal Server Error');
  });

  it('结构化 detail 优先于状态码推断', async () => {
    stubFetchResponse(
      new Response(JSON.stringify({ detail: 'unknown pool' }), {
        status: 400,
        headers: { 'content-type': 'application/json' },
      }),
    );

    await expect(fetchPoolBoard('nope')).rejects.toThrow('unknown pool');
  });
});
