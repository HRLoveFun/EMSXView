import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * 声明式取数 hook —— 仓库内的最小「数据获取层」，不引入外部依赖。
 *
 * 为什么需要它
 * ------------
 * 手写 `useEffect(() => { setIsLoading(true); void load() }, [deps])` 会命中
 * `react-hooks/set-state-in-effect`（effect 同步体内 setState ⇒ 级联渲染）。
 * 本 hook 把该模式收敛到一处，并按规则允许的形态实现：
 *
 * - **loading 由 key 派生**（数据还没对应当前 key 即为加载中），不在 effect 内同步 setState；
 * - **setState 只出现在 Promise 回调中**（规则明确允许「订阅外部来源后在其回调里 setState」）；
 * - 旧请求用 `cancelled` 标记丢弃，并在下次 key 变化 / 卸载时清理。
 *
 * 语义与「手写版」一致：key 变化即重新拉取；`key === null` 表示本次不拉取（如对话框关闭）。
 *
 * @param key    取数键：变化即重新拉取（建议用可比较的字符串；`null` = 跳过）
 * @param loader 纯取数函数：**不得在内部 setState**（状态更新交给本 hook → 这是本 hook 存在的意义）
 * @param onData 可选：数据到达时的回调（在 Promise 回调内执行，供「取到数据后同步本地可编辑 state」等场景）
 */
export function useAsyncData<T>(
  key: string | null,
  loader: () => Promise<T>,
  onData?: (data: T) => void,
): AsyncDataResult<T> {
  // 结果连同「它属于哪个 key / 哪次 reload」一起存，便于派生 loading
  const [result, setResult] = useState<AsyncDataState<T> | null>(null);
  const [nonce, setNonce] = useState(0);

  // 始终指向最新 loader / onData：在 effect 内更新 ref（渲染期不写字，避免 react-hooks/refs）
  const loaderRef = useRef(loader);
  const onDataRef = useRef(onData);
  useEffect(() => {
    loaderRef.current = loader;
    onDataRef.current = onData;
  });

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    loaderRef.current().then(
      (data) => {
        if (cancelled) return;
        setResult({ key, nonce, data });
        onDataRef.current?.(data);
      },
      (err: unknown) => {
        if (cancelled) return;
        setResult({ key, nonce, error: err instanceof Error ? err : new Error(String(err)) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  const isFresh = result !== null && result.key === key && result.nonce === nonce;

  return {
    // 数据保留到下次取数成功为止（与手写版「保留上一次数据」一致）
    data: result?.data,
    error: isFresh ? (result.error ?? null) : null,
    isLoading: key !== null && !isFresh,
    reload,
  };
}

export interface AsyncDataResult<T> {
  /** 最近一次成功的数据（尚未成功过则为 undefined） */
  data: T | undefined;
  /** 当前 key 对应的错误（无错或数据尚未对应当前 key 时为 null） */
  error: Error | null;
  /** 派生：当前 key 的数据尚未就绪（含首次加载与 reload 进行中） */
  isLoading: boolean;
  /** 手动重取（同一 key 重新拉取）；事件处理器可直接调用 */
  reload: () => void;
}

interface AsyncDataState<T> {
  key: string;
  nonce: number;
  data?: T;
  error?: Error;
}
