/**
 * MarketView 实时行情流 hook（057 DL-15 / DL-29 实时列）。
 *
 * 数据路径：core 后端 mktdata 订阅缓存 → `/ws/market-state` 推送 → 本 hook。
 * 策略：
 * 1. 挂载/白名单变化时先用 REST 拉一帧（首屏不空等第一个推送）；
 * 2. 向 core 注册池内标的的 mktdata 订阅（前端不直连 Bloomberg）；
 * 3. 打开 WS 接收 5 秒一次的推送；WS 断线期间降级为 5 秒 REST 轮询，
 *    重连成功后停止轮询。
 *
 * setState 只出现在 Promise / 订阅回调里（不在 effect 同步体内），
 * 以符合 `react-hooks/set-state-in-effect` 规则。
 */

import { useEffect, useMemo, useState } from 'react';

import type { LiveMarketStateStatus, MarketStateSnapshot } from '../types';
import {
  fetchMarketStateSnapshot,
  resolveMarketStateStreamUrl,
  subscribeMarketState,
} from '../services/api';
import { createMarketStateStream } from '../services/market-state-stream';
import type { MarketStateStream } from '../services/market-state-stream';

/** WS 打开前的合并窗口：股票池与快照分两批到达时只建一条连接。 */
const STREAM_DEBOUNCE_MS = 400;
/** WS 不可用时的 REST 轮询间隔（与服务端推送节奏一致）。 */
const POLL_INTERVAL_MS = 5_000;

export interface LiveMarketState {
  /** 最近一帧实时快照（WS 或 REST，字段形状相同）。 */
  snapshot: MarketStateSnapshot | null;
  /** live = WS 推送；polling = WS 不可用、REST 轮询；connecting = 尚无数据。 */
  status: LiveMarketStateStatus;
  /** 最近一次取数失败信息（成功后清空）。 */
  error: string | null;
}

export function useMarketStateStream(tickers: string[]): LiveMarketState {
  // 白名单按键排序去重：同一批标的的不同顺序不应触发重连
  const tickerKey = useMemo(
    () => Array.from(new Set(tickers.filter(Boolean))).sort().join(','),
    [tickers],
  );
  const [snapshot, setSnapshot] = useState<MarketStateSnapshot | null>(null);
  const [status, setStatus] = useState<LiveMarketStateStatus>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tickerKey) return;
    const list = tickerKey.split(',');

    let cancelled = false;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let connectTimer: ReturnType<typeof setTimeout> | null = null;
    let stream: MarketStateStream | null = null;

    const stopPolling = (): void => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const loadOnce = async (): Promise<void> => {
      try {
        const data = await fetchMarketStateSnapshot(list);
        if (!cancelled) {
          setSnapshot(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load market state');
        }
      }
    };

    const startPolling = (): void => {
      if (pollTimer) return;
      pollTimer = setInterval(() => {
        void loadOnce();
      }, POLL_INTERVAL_MS);
    };

    // 首帧 + mktdata 订阅注册（后端按白名单订阅，MarketView 不直连 Bloomberg）
    void loadOnce();
    void subscribeMarketState(list).catch(() => undefined);

    connectTimer = setTimeout(() => {
      connectTimer = null;
      stream = createMarketStateStream({
        url: resolveMarketStateStreamUrl(list),
        onSnapshot: (data) => {
          if (cancelled) return;
          setSnapshot(data);
          setError(null);
        },
        onStatus: (next) => {
          if (cancelled) return;
          if (next === 'open') {
            setStatus('live');
            stopPolling();
            return;
          }
          if (next === 'closed') {
            setStatus('polling');
            startPolling();
            return;
          }
          // connecting：已进入 live/polling 后不因重连抖动把状态打回未就绪
          setStatus((current) =>
            current === 'live' || current === 'polling' ? current : 'connecting',
          );
        },
      });
    }, STREAM_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      if (connectTimer) clearTimeout(connectTimer);
      stopPolling();
      stream?.close();
    };
  }, [tickerKey]);

  return { snapshot, status, error };
}
