import { afterEach, describe, expect, it, vi } from 'vitest';

import { createMarketStateStream, parseMarketStateMessage } from './market-state-stream';
import type { MarketStateStreamStatus } from './market-state-stream';

const snapshot = {
  as_of: '2026-10-27T10:00:00',
  enabled: true,
  tickers: [],
  thresholds: {},
  schema_version: 'market-state-v2',
};

/** 可控的 WebSocket 替身：测试里手动触发 open/message/close。 */
class FakeSocket {
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  close = vi.fn();
  url: string;

  constructor(url: string) {
    this.url = url;
  }

  open(): void {
    this.onopen?.(new Event('open'));
  }

  receive(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }

  drop(): void {
    this.onclose?.(new Event('close') as CloseEvent);
  }
}

const buildFactory = () => {
  const sockets: FakeSocket[] = [];
  const factory = (url: string): WebSocket => {
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket as unknown as WebSocket;
  };
  return { sockets, factory };
};

afterEach(() => {
  vi.useRealTimers();
});

describe('parseMarketStateMessage', () => {
  it('extracts the data payload from market_state events', () => {
    const parsed = parseMarketStateMessage(JSON.stringify({ type: 'market_state', data: snapshot }));
    expect(parsed?.schema_version).toBe('market-state-v2');
  });

  it('ignores other gateway events (order/route deltas share the connection)', () => {
    expect(parseMarketStateMessage(JSON.stringify({ type: 'order', data: {} }))).toBeNull();
  });

  it('returns null for malformed payloads instead of throwing', () => {
    expect(parseMarketStateMessage('not-json')).toBeNull();
    expect(parseMarketStateMessage(JSON.stringify({ type: 'market_state' }))).toBeNull();
  });
});

describe('createMarketStateStream', () => {
  it('reports connecting → open and forwards snapshots', () => {
    const { sockets, factory } = buildFactory();
    const onSnapshot = vi.fn();
    const statuses: MarketStateStreamStatus[] = [];

    const stream = createMarketStateStream({
      url: 'ws://localhost:3000/ws/market-state?tickers=AAPL%20US%20Equity',
      onSnapshot,
      onStatus: (status) => statuses.push(status),
      buildSocket: factory,
    });

    expect(sockets).toHaveLength(1);
    sockets[0].open();
    sockets[0].receive({ type: 'market_state', data: snapshot });

    expect(statuses).toEqual(['connecting', 'open']);
    expect(onSnapshot).toHaveBeenCalledWith(expect.objectContaining({ enabled: true }));
    expect(stream.status).toBe('open');
  });

  it('reconnects with backoff after an unexpected close', () => {
    vi.useFakeTimers();
    const { sockets, factory } = buildFactory();
    const statuses: MarketStateStreamStatus[] = [];

    createMarketStateStream({
      url: 'ws://localhost:3000/ws/market-state',
      onSnapshot: vi.fn(),
      onStatus: (status) => statuses.push(status),
      reconnectBaseMs: 1_000,
      buildSocket: factory,
    });

    sockets[0].open();
    sockets[0].drop();
    expect(statuses).toEqual(['connecting', 'open', 'closed']);

    vi.advanceTimersByTime(1_000);
    expect(sockets).toHaveLength(2);
  });

  it('does not reconnect after close() is called', () => {
    vi.useFakeTimers();
    const { sockets, factory } = buildFactory();

    const stream = createMarketStateStream({
      url: 'ws://localhost:3000/ws/market-state',
      onSnapshot: vi.fn(),
      buildSocket: factory,
    });

    stream.close();
    expect(sockets[0].close).toHaveBeenCalled();

    vi.advanceTimersByTime(5_000);
    expect(sockets).toHaveLength(1);
  });

  it('reports closed and retries when the socket cannot be constructed', () => {
    vi.useFakeTimers();
    const statuses: MarketStateStreamStatus[] = [];
    let attempts = 0;

    createMarketStateStream({
      url: 'ws://localhost:3000/ws/market-state',
      onSnapshot: vi.fn(),
      onStatus: (status) => statuses.push(status),
      reconnectBaseMs: 100,
      buildSocket: () => {
        attempts += 1;
        throw new Error('boom');
      },
    });

    expect(statuses).toEqual(['connecting', 'closed']);
    vi.advanceTimersByTime(100);
    expect(attempts).toBe(2);
  });
});
