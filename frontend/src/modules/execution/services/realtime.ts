/**
 * WebSocket realtime transport — re-exports from the canonical shared copy.
 *
 * All usage sites import from `@execution/services/realtime` for backward
 * compatibility. This barrel re-export ensures a single source of truth
 * at `@shared/services/realtime`.
 *
 * DEPRECATED: New code should import directly from `@shared/services/realtime`.
 */
export {
  type DeltaEvent,
  type ConnectedEvent,
  type ReplayDoneEvent,
  type DeltaHandler,
  type StatusHandler,
  type RealtimeClientOptions,
  type RealtimeClient,
  createRealtimeClient,
} from '@shared/services/realtime';
