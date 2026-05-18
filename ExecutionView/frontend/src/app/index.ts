// App shell — centralized re-export
export { default as App } from './App';
export { AppShell } from './AppShell';
export { AuthProvider, useAuth } from './providers/AuthProvider';
export { ToastProvider, useToast } from './providers/ToastProvider';
export { RealtimeProvider, useRealtime } from './providers/RealtimeProvider';