/**
 * Shell Context — React context providing shell-level services to all modules.
 *
 * Modules consume `useShellContext()` to access navigation, toast notifications,
 * realtime connection state, and other shell services without receiving them as props.
 */

import { createContext, useContext } from 'react';
import type { ModuleId } from './module-registry';

// ── Types ──────────────────────────────────────────────────────────────────

/** Modes for the subscriptions-warming UI notice shown during Bloomberg startup. */
export type ShellWarmingMode = 'initial' | 'reconnecting' | 'timed-out';

/** Shell-level services available to every module via React context. */
export interface ShellContextValue {
  /** Navigate to another workspace module tab. */
  navigateTo: (moduleId: ModuleId) => void;
  /** Post a toast notification (shown in the shell's toast container). */
  addToast: (type: 'info' | 'success' | 'error', message: string) => void;
  /** Current WebSocket realtime client (null until connected). */
  realtimeClient: unknown | null;
  /** Whether the realtime WebSocket is currently connected. */
  streamConnected: boolean;
  /** Whether the realtime WebSocket has ever connected since page load. */
  streamEverConnected: boolean;
  /** Bloomberg subscriptions are still being warmed (no data yet). */
  subscriptionsWarming: boolean;
  /** Current warming mode for the startup notice. */
  subscriptionsWarmingMode: ShellWarmingMode;
  /** Logout handler — clears token and resets auth state. */
  logout: () => void;
}

// ── Context ────────────────────────────────────────────────────────────────

export const ShellContext = createContext<ShellContextValue | null>(null);

/** Hook to access shell services from any module component. */
export function useShellContext(): ShellContextValue {
  const ctx = useContext(ShellContext);
  if (!ctx) {
    throw new Error(
      'useShellContext must be used within a <ShellContext.Provider>. ' +
      'Ensure your component is mounted inside the AppShell.',
    );
  }
  return ctx;
}
