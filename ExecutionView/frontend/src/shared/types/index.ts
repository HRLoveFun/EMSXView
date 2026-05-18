// ============================================================================
// Shared Types — Cross-domain types used by multiple modules
// ============================================================================

// Toast notification
export interface Toast {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
  duration?: number;
}

// API Response types
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

// Connection status
export type ConnectionStatus = 'connected' | 'disconnected' | 'pending';
export type BloombergConnectionState = 'connected' | 'disconnected' | 'connecting' | 'error';
export type StartupPhase = 'backend_starting' | 'bloomberg_connecting' | 'subscriptions_warming' | 'ready' | 'error';

export interface BackendStartupSnapshot {
  httpReady: boolean;
  startedAt?: string | null;
  uptime?: number | null;
}

export interface BloombergStartupSnapshot {
  status: BloombergConnectionState;
  message?: string;
  lastConnected?: string | null;
  uptime?: number | null;
}

export interface SubscriptionStartupSnapshot {
  ordersInitPaintDone: boolean;
  routesInitPaintDone: boolean;
  subscriptionFailed: boolean;
  marketDataConnected: boolean;
  orderCount: number;
  routeCount: number;
  ready: boolean;
}

export interface StartupStatusSnapshot {
  phase: StartupPhase;
  ready: boolean;
  message?: string;
  backend: BackendStartupSnapshot;
  bloomberg: BloombergStartupSnapshot;
  subscriptions: SubscriptionStartupSnapshot;
}