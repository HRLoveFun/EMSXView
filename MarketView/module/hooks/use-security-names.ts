/**
 * 证券名称（`SHORT_NAME` 英文短名）——按 ticker 批量取一次、模块内缓存。
 *
 * 名称是静态参考数据，不随行情变化：只在出现新 ticker 时请求增量，
 * 失败静默（列显示 `—`），不阻塞面板渲染。
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import { fetchSecurityNames } from '../services/api';

export function useSecurityNames(tickers: string[]): Map<string, string> {
  const [resolved, setResolved] = useState<Record<string, string>>({});
  const cacheRef = useRef<Record<string, string>>({});

  // ticker 集合做去重+排序后作为 key：池板/盘前单顺序变化不会触发重新请求
  const key = useMemo(
    () => Array.from(new Set(tickers.filter(Boolean))).sort().join(','),
    [tickers],
  );

  useEffect(() => {
    if (!key) return;
    const wanted = key.split(',');
    const missing = wanted.filter((ticker) => !(ticker in cacheRef.current));
    if (!missing.length) return;

    let cancelled = false;
    fetchSecurityNames(missing)
      .then((data) => {
        if (cancelled || !data?.names) return;
        cacheRef.current = { ...cacheRef.current, ...data.names };
        setResolved(cacheRef.current);
      })
      .catch(() => {
        // 名称是锦上添花：终端不可用时列显示 —，不影响行情与成本列
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  return useMemo(() => new Map(Object.entries(resolved)), [resolved]);
}
