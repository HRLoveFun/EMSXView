/**
 * Tests for the realtime WebSocket client, order-stream-store, and route-stream-store.
 *
 * Run: npx vitest run src/services/realtime.test.ts
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createRealtimeClient, type DeltaEvent } from './realtime';
import { createOrderStreamStore } from '@/stores/order-stream-store';
import { createRouteStreamStore } from '@/stores/route-stream-store';

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

type WSHandler = ((ev: { data: string }) => void) | null;

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;

  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: WSHandler = null;
  onerror: (() => void) | null = null;

  sent: string[] = [];

  constructor(_url: string) {
    // Auto-fire open on next tick
    queueMicrotask(() => this.onopen?.());
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
  }

  // Test helpers
  simulateMessage(payload: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  simulateClose() {
    this.onclose?.();
  }
}

// ---------------------------------------------------------------------------
// createRealtimeClient tests
// ---------------------------------------------------------------------------

describe('createRealtimeClient', () => {
  let instances: MockWebSocket[];

  beforeEach(() => {
    instances = [];
    vi.stubGlobal('WebSocket', class extends MockWebSocket {
      constructor(url: string) {
        super(url);
        instances.push(this);
      }
    });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function lastWs(): MockWebSocket {
    return instances[instances.length - 1];
  }

  it('connects and fires status handlers', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    const statuses: string[] = [];
    client.onStatus((s) => statuses.push(s));
    client.connect();
    await vi.advanceTimersByTimeAsync(0); // flush microtask (onopen)
    expect(statuses).toContain('connecting');
    expect(statuses).toContain('connected');
    expect(client.connected).toBe(true);
  });

  it('routes order delta events to order handlers', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    const events: DeltaEvent[] = [];
    client.on('order', (e) => events.push(e));
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    lastWs().simulateMessage({
      type: 'update', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1', symbol: 'AAPL' },
    });

    expect(events).toHaveLength(1);
    expect(events[0].entity).toBe('order');
    expect(events[0].key).toBe('1');
  });

  it('routes route delta events to route handlers', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    const events: DeltaEvent[] = [];
    client.on('route', (e) => events.push(e));
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    lastWs().simulateMessage({
      type: 'update', entity: 'route', key: '1.1', cursor: 2,
      version: 1, ts: Date.now(), data: { id: '1.1' },
    });

    expect(events).toHaveLength(1);
    expect(events[0].entity).toBe('route');
  });

  it('does not route order events to route handlers', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    const routeEvents: DeltaEvent[] = [];
    client.on('route', (e) => routeEvents.push(e));
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    lastWs().simulateMessage({
      type: 'update', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1' },
    });

    expect(routeEvents).toHaveLength(0);
  });

  it('updates cursor from delta events', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    lastWs().simulateMessage({
      type: 'update', entity: 'order', key: '1', cursor: 42,
      version: null, ts: Date.now(), data: {},
    });

    expect(client.cursor).toBe(42);
  });

  it('requests replay on reconnect when cursor gap exists', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws', reconnectBaseMs: 100 });
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    // Simulate some events to advance cursor
    lastWs().simulateMessage({
      type: 'update', entity: 'order', key: '1', cursor: 5,
      version: null, ts: Date.now(), data: {},
    });
    expect(client.cursor).toBe(5);

    // Simulate disconnect + reconnect
    lastWs().simulateClose();
    vi.advanceTimersByTime(200); // trigger reconnect
    await vi.advanceTimersByTimeAsync(0); // onopen

    // New WS should receive a connected message with higher cursor
    const newWs = lastWs();
    newWs.simulateMessage({ type: 'connected', cursor: 10, timestamp: new Date().toISOString() });

    // Client should have sent a replay request
    const replayMsg = newWs.sent.find((s) => JSON.parse(s).action === 'replay');
    expect(replayMsg).toBeDefined();
    const parsed = JSON.parse(replayMsg!);
    expect(parsed.cursor).toBe(5);
  });

  it('unsubscribes handlers via returned dispose function', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws' });
    const events: DeltaEvent[] = [];
    const unsub = client.on('order', (e) => events.push(e));
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    unsub();

    lastWs().simulateMessage({
      type: 'update', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: {},
    });

    expect(events).toHaveLength(0);
  });

  it('sends heartbeat pings at configured interval', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws', heartbeatMs: 500 });
    client.connect();
    await vi.advanceTimersByTimeAsync(0);

    vi.advanceTimersByTime(1100); // 2 heartbeats
    const pings = lastWs().sent.filter((s) => JSON.parse(s).action === 'ping');
    expect(pings.length).toBeGreaterThanOrEqual(2);
  });

  it('intentional disconnect prevents reconnect', async () => {
    const client = createRealtimeClient({ url: 'ws://test/ws', reconnectBaseMs: 50 });
    client.connect();
    await vi.advanceTimersByTimeAsync(0);
    const initialCount = instances.length;

    client.disconnect();
    vi.advanceTimersByTime(5000);

    expect(instances.length).toBe(initialCount); // no new connections
    expect(client.connected).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// OrderStreamStore tests
// ---------------------------------------------------------------------------

describe('OrderStreamStore', () => {
  it('applies snapshot events', () => {
    const store = createOrderStreamStore();
    store.apply({
      type: 'snapshot', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1', symbol: 'AAPL' },
    } as DeltaEvent);

    expect(store.size).toBe(1);
    expect(store.snapshot()[0]).toMatchObject({ id: '1', symbol: 'AAPL' });
  });

  it('merges update events into existing orders', () => {
    const store = createOrderStreamStore();
    store.apply({
      type: 'snapshot', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1', symbol: 'AAPL', qty: 100 },
    } as DeltaEvent);

    store.apply({
      type: 'update', entity: 'order', key: '1', cursor: 2,
      version: null, ts: Date.now(), data: { id: '1', qty: 200 },
    } as DeltaEvent);

    const order = store.snapshot()[0];
    expect(order).toMatchObject({ id: '1', symbol: 'AAPL', qty: 200 });
  });

  it('handles delete events', () => {
    const store = createOrderStreamStore();
    store.apply({
      type: 'snapshot', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1' },
    } as DeltaEvent);

    const deleted = store.apply({
      type: 'delete', entity: 'order', key: '1', cursor: 2,
      version: null, ts: Date.now(), data: {},
    } as DeltaEvent);

    expect(deleted).toBe(true);
    expect(store.size).toBe(0);
  });

  it('reset replaces all orders', () => {
    const store = createOrderStreamStore();
    store.apply({
      type: 'snapshot', entity: 'order', key: '1', cursor: 1,
      version: null, ts: Date.now(), data: { id: '1' },
    } as DeltaEvent);

    store.reset([{ id: '2' }, { id: '3' }] as any);
    expect(store.size).toBe(2);
    expect(store.snapshot().map((o) => o.id)).toEqual(['2', '3']);
  });
});

// ---------------------------------------------------------------------------
// RouteStreamStore tests
// ---------------------------------------------------------------------------

describe('RouteStreamStore', () => {
  it('applies snapshot and merges updates', () => {
    const store = createRouteStreamStore();
    store.apply({
      type: 'snapshot', entity: 'route', key: '1.1', cursor: 1,
      version: 1, ts: Date.now(), data: { id: '1.1', broker: 'GS' },
    } as DeltaEvent);

    store.apply({
      type: 'update', entity: 'route', key: '1.1', cursor: 2,
      version: 2, ts: Date.now(), data: { id: '1.1', status: 'filled' },
    } as DeltaEvent);

    const route = store.snapshot()[0];
    expect(route).toMatchObject({ id: '1.1', broker: 'GS', status: 'filled' });
  });

  it('reset replaces all routes', () => {
    const store = createRouteStreamStore();
    store.reset([{ id: '1.1' }, { id: '2.1' }] as any);
    expect(store.size).toBe(2);
  });
});
