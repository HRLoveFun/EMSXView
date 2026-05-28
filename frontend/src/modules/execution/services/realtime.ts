/**
 * Re-export from shared/services/realtime.ts — the canonical location.
 *
 * All types and createRealtimeClient are now defined in @shared/services/realtime.
 * This module exists for backward compatibility with existing imports from @execution/services/realtime.
 */

export {
  type ConnectedEvent,
  type DeltaEvent,
  type DeltaHandler,
  type RealtimeClient,
  type RealtimeClientOptions,
  type ReplayDoneEvent,
  type StatusHandler,
  createRealtimeClient,
} from '@shared/services/realtime';
