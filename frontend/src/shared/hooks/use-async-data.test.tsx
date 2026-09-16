/**
 * useAsyncData 契约测试（specs/022-t11-async-data-layer）。
 *
 * 关注点：loading 必须由 key 派生（而非 effect 内 setState）、key 变化重取、
 * key=null 跳过、reload 重取、错误暴露、onData 回调时机、旧请求结果被丢弃。
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useAsyncData } from './use-async-data';

/** 可控 Promise：手动决定何时 resolve，用于观察中间态 */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useAsyncData', () => {
  it('首次加载：isLoading 为真，数据到达后为假并给出 data', async () => {
    const d = deferred<string>();
    const { result } = renderHook(() => useAsyncData('k1', () => d.promise));

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();

    await act(async () => {
      d.resolve('value-1');
      await d.promise;
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBe('value-1');
    expect(result.current.error).toBeNull();
  });

  it('key 变化：立刻回到加载态，并以新 key 的结果替换 data', async () => {
    const loader = vi.fn((key: string) => Promise.resolve(`value-${key}`));
    const { result, rerender } = renderHook(({ key }) => useAsyncData(key, () => loader(key)), {
      initialProps: { key: 'k1' },
    });

    await waitFor(() => expect(result.current.data).toBe('value-k1'));

    rerender({ key: 'k2' });
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => expect(result.current.data).toBe('value-k2'));
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('key=null：不拉取、不处于加载态（对话框关闭等场景）', async () => {
    const loader = vi.fn(() => Promise.resolve('never'));
    const { result } = renderHook(() => useAsyncData(null, loader));

    expect(result.current.isLoading).toBe(false);
    expect(loader).not.toHaveBeenCalled();
  });

  it('reload()：同一 key 重新拉取', async () => {
    const loader = vi.fn(() => Promise.resolve('v'));
    const { result } = renderHook(() => useAsyncData('k', loader));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(loader).toHaveBeenCalledTimes(1);

    act(() => result.current.reload());
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(loader).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
  });

  it('失败：暴露 error 且结束加载态（非 Error 抛出被包装）', async () => {
    const { result } = renderHook(() => useAsyncData('k', () => Promise.reject(new Error('boom'))));

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error?.message).toBe('boom');
    expect(result.current.isLoading).toBe(false);

    const { result: thrown } = renderHook(() => useAsyncData('k', () => Promise.reject('plain')));
    await waitFor(() => expect(thrown.current.error).not.toBeNull());
    expect(thrown.current.error?.message).toBe('plain');
  });

  it('onData：数据到达时以其为参数调用一次（供同步本地可编辑 state）', async () => {
    const onData = vi.fn();
    const { result } = renderHook(() => useAsyncData('k', () => Promise.resolve(42), onData));

    await waitFor(() => expect(result.current.data).toBe(42));
    expect(onData).toHaveBeenCalledWith(42);
    expect(onData).toHaveBeenCalledTimes(1);
  });

  it('key 变化后旧请求的结果被丢弃（不覆盖新 key 的数据）', async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { result, rerender } = renderHook(
      ({ key }) => useAsyncData(key, () => (key === 'k1' ? first.promise : second.promise)),
      { initialProps: { key: 'k1' } },
    );

    rerender({ key: 'k2' });

    await act(async () => {
      second.resolve('new');
      await second.promise;
    });
    await waitFor(() => expect(result.current.data).toBe('new'));

    // 旧 key 的请求晚到：不得覆盖
    await act(async () => {
      first.resolve('stale');
      await first.promise;
    });
    expect(result.current.data).toBe('new');
  });
});
