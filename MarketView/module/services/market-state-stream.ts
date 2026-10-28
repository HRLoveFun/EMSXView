/**
 * 盘中市场状态 WebSocket 客户端（057 DL-15 / 实时列）。
 *
 * 服务端 core 后端 `/ws/market-state` 每 5 秒推送一次 `{"type":"market_state","data":…}`；
 * 同一条连接还会收到订单/路由增量事件（网关共用连接注册表），本客户端只消费
 * `market_state`，其余类型一律忽略。断线按指数退避重连，由调用方决定何时降级为
 * REST 轮询（见 `useMarketStateStream`）。
 */

import type { MarketStateSnapshot } from '../types';

export type MarketStateStreamStatus = 'connecting' | 'open' | 'closed';

export interface MarketStateStream {
  /** 主动关闭（不再重连）。 */
  close(): void;
  readonly status: MarketStateStreamStatus;
}

export interface MarketStateStreamOptions {
  /** 完整 WebSocket 地址（含 tickers 白名单查询串）。 */
  url: string;
  onSnapshot: (snapshot: MarketStateSnapshot) => void;
  onStatus?: (status: MarketStateStreamStatus) => void;
  /** 重连退避基数（ms，指数增长，上限 30s）。 */
  reconnectBaseMs?: number;
  /** 测试注入的 WebSocket 构造器（缺省用全局 WebSocket）。 */
  buildSocket?: (url: string) => WebSocket;
}

/** 解析一条 WS 文本消息；非 market_state 事件或坏数据返回 null。 */
export function parseMarketStateMessage(raw: string): MarketStateSnapshot | null {
  let message: { type?: string; data?: unknown };
  try {
    message = JSON.parse(raw) as { type?: string; data?: unknown };
  } catch {
    return null;
  }
  if (!message || message.type !== 'market_state' || !message.data) {
    return null;
  }
  return message.data as MarketStateSnapshot;
}

export function createMarketStateStream(opts: MarketStateStreamOptions): MarketStateStream {
  const { url, onSnapshot, onStatus, reconnectBaseMs = 1_000, buildSocket } = opts;
  const socketFactory =
    buildSocket ?? (typeof WebSocket === 'undefined' ? null : (target: string) => new WebSocket(target));

  let socket: WebSocket | null = null;
  let status: MarketStateStreamStatus = 'closed';
  let attempts = 0;
  let closed = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const notify = (next: MarketStateStreamStatus): void => {
    status = next;
    onStatus?.(next);
  };

  const scheduleReconnect = (): void => {
    if (closed) return;
    const delay = Math.min(reconnectBaseMs * 2 ** attempts, 30_000);
    attempts += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  };

  function connect(): void {
    if (closed) return;
    if (!socketFactory) {
      // 运行环境没有 WebSocket（如 SSR / 测试桩缺失）：直接置 closed，让调用方回落轮询
      notify('closed');
      return;
    }

    notify('connecting');
    let next: WebSocket;
    try {
      next = socketFactory(url);
    } catch {
      notify('closed');
      scheduleReconnect();
      return;
    }
    socket = next;

    next.onopen = () => {
      attempts = 0;
      notify('open');
    };
    next.onmessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return;
      const snapshot = parseMarketStateMessage(event.data);
      if (snapshot) onSnapshot(snapshot);
    };
    next.onerror = () => {
      // onclose 随后触发，重连逻辑统一在那里处理
    };
    next.onclose = () => {
      socket = null;
      if (closed) return;
      notify('closed');
      scheduleReconnect();
    };
  }

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (socket) {
        socket.onopen = null;
        socket.onmessage = null;
        socket.onclose = null;
        socket.close();
        socket = null;
      }
      status = 'closed';
    },
    get status() {
      return status;
    },
  };
}
