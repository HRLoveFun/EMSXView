/**
 * WebSocket realtime transport with automatic reconnect, heartbeat, and cursor resume.
 *
 * Usage:
 *   const rt = createRealtimeClient({ url: 'ws://localhost:3000/ws/orders' });
 *   rt.on('order', (evt) => { ... });
 *   rt.on('route', (evt) => { ... });
 *   rt.connect();
 *
 * NOTE: This is the canonical shared copy. The @execution/services/realtime module
 * re-exports from here for backward compatibility.
 */

export interface DeltaEvent {
  type: 'snapshot' | 'update' | 'delete';
  entity: 'order' | 'route';
  key: string;
  version: number | null;
  ts: number;
  cursor: number;
  data: Record<string, unknown>;
}

export interface ConnectedEvent {
  type: 'connected';
  cursor: number;
  timestamp: string;
}

export interface ReplayDoneEvent {
  type: 'replay_done';
  replayed: number;
  cursor: number;
}

type MessagePayload = DeltaEvent | ConnectedEvent | ReplayDoneEvent | { type: string; [k: string]: unknown };

export type DeltaHandler = (event: DeltaEvent) => void;
export type StatusHandler = (status: 'connecting' | 'connected' | 'disconnected') => void;

export interface RealtimeClientOptions {
  /** WebSocket URL, e.g. ws://localhost:3000/ws/orders */
  url: string;
  /** Heartbeat interval in ms (default 15000) */
  heartbeatMs?: number;
  /** Max reconnect attempts before giving up (0 = infinite) */
  maxReconnects?: number;
  /** Base reconnect delay in ms (doubles each attempt, capped at 30s) */
  reconnectBaseMs?: number;
}

export interface RealtimeClient {
  connect(): void;
  disconnect(): void;
  /**
   * Force an immediate reconnection. Resets backoff and tears down any
   * existing socket. Useful when the page returns from being hidden and
   * the underlying WebSocket may have been silently throttled / closed
   * by the browser without firing onclose synchronously.
   */
  forceReconnect(): void;
  on(entity: 'order' | 'route', handler: DeltaHandler): () => void;
  onStatus(handler: StatusHandler): () => void;
  readonly connected: boolean;
  readonly cursor: number;
  /** True once the socket has reached OPEN at least once in this session. */
  readonly everConnected: boolean;
}

export function createRealtimeClient(opts: RealtimeClientOptions): RealtimeClient {
  const {
    url,
    heartbeatMs = 15_000,
    maxReconnects = 0,
    reconnectBaseMs = 1_000,
  } = opts;

  let ws: WebSocket | null = null;
  let _connected = false;
  let _everConnected = false;
  let _cursor = 0;
  let _reconnectAttempt = 0;
  let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  let _intentionalClose = false;

  const orderHandlers = new Set<DeltaHandler>();
  const routeHandlers = new Set<DeltaHandler>();
  const statusHandlers = new Set<StatusHandler>();

  function notifyStatus(s: 'connecting' | 'connected' | 'disconnected') {
    statusHandlers.forEach((h) => h(s));
  }

  function handleMessage(raw: string) {
    let msg: MessagePayload;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    if (msg.type === 'connected') {
      const c = msg as ConnectedEvent;
      if (_cursor > 0 && _cursor < c.cursor) {
        ws?.send(JSON.stringify({ action: 'replay', cursor: _cursor }));
      } else {
        _cursor = c.cursor;
      }
      return;
    }

    if (msg.type === 'replay_done') {
      const r = msg as ReplayDoneEvent;
      _cursor = r.cursor;
      return;
    }

    if (msg.type === 'pong') return;

    // Delta event
    const delta = msg as DeltaEvent;
    if (delta.cursor) _cursor = delta.cursor;

    if (delta.entity === 'order') {
      orderHandlers.forEach((h) => h(delta));
    } else if (delta.entity === 'route') {
      routeHandlers.forEach((h) => h(delta));
    }
  }

  function startHeartbeat() {
    stopHeartbeat();
    _heartbeatTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'ping' }));
      }
    }, heartbeatMs);
  }

  function stopHeartbeat() {
    if (_heartbeatTimer) {
      clearInterval(_heartbeatTimer);
      _heartbeatTimer = null;
    }
  }

  function scheduleReconnect() {
    if (_intentionalClose) return;
    if (maxReconnects > 0 && _reconnectAttempt >= maxReconnects) return;

    const delay = Math.min(reconnectBaseMs * 2 ** _reconnectAttempt, 30_000);
    _reconnectAttempt++;
    _reconnectTimer = setTimeout(() => doConnect(), delay);
  }

  function doConnect() {
    if (_reconnectTimer) {
      clearTimeout(_reconnectTimer);
      _reconnectTimer = null;
    }

    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return;
    }

    notifyStatus('connecting');

    try {
      ws = new WebSocket(url);
    } catch {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      _connected = true;
      _everConnected = true;
      _reconnectAttempt = 0;
      notifyStatus('connected');
      startHeartbeat();
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') handleMessage(ev.data);
    };

    ws.onclose = () => {
      _connected = false;
      stopHeartbeat();
      notifyStatus('disconnected');
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose will fire after onerror — reconnect handled there
    };
  }

  return {
    connect() {
      _intentionalClose = false;
      _reconnectAttempt = 0;
      doConnect();
    },

    disconnect() {
      _intentionalClose = true;
      stopHeartbeat();
      if (_reconnectTimer) clearTimeout(_reconnectTimer);
      if (ws) {
        ws.onclose = null;
        ws.close();
        ws = null;
      }
      _connected = false;
      notifyStatus('disconnected');
    },

    forceReconnect() {
      _intentionalClose = false;
      _reconnectAttempt = 0;
      stopHeartbeat();
      if (_reconnectTimer) {
        clearTimeout(_reconnectTimer);
        _reconnectTimer = null;
      }
      if (ws) {
        try {
          ws.onclose = null;
          ws.close();
        } catch {
          /* ignore */
        }
        ws = null;
      }
      _connected = false;
      doConnect();
    },

    on(entity: 'order' | 'route', handler: DeltaHandler) {
      const set = entity === 'order' ? orderHandlers : routeHandlers;
      set.add(handler);
      return () => { set.delete(handler); };
    },

    onStatus(handler: StatusHandler) {
      statusHandlers.add(handler);
      return () => { statusHandlers.delete(handler); };
    },

    get connected() {
      return _connected;
    },

    get cursor() {
      return _cursor;
    },

    get everConnected() {
      return _everConnected;
    },
  };
}
