// Realtime WebSocket connection context — manages WS lifecycle
import { createContext, useContext, useState, useEffect, useRef, type ReactNode } from 'react';
import { createRealtimeClient, type RealtimeClient } from '@execution/services/realtime';
import { useToast } from './ToastProvider';

interface RealtimeContextValue {
  client: RealtimeClient | null;
  streamConnected: boolean;
  streamEverConnected: boolean;
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null);

export function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext);
  if (!ctx) throw new Error('useRealtime must be used within RealtimeProvider');
  return ctx;
}

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { addToast } = useToast();
  const [streamConnected, setStreamConnected] = useState(false);
  const [streamEverConnected, setStreamEverConnected] = useState(false);
  const [client, setClient] = useState<RealtimeClient | null>(null);
  const clientRef = useRef<RealtimeClient | null>(null);

  useEffect(() => {
    // Build WS URL from current page location (works behind proxy).
    // Security: when serving over HTTPS we must connect via WSS.
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const envUrl = import.meta.env.VITE_API_URL;
    let wsBase: string;
    if (envUrl) {
      const isPageSecure = window.location.protocol === 'https:';
      const envIsInsecure = /^http:\/\//i.test(envUrl) || /^ws:\/\//i.test(envUrl);
      if (isPageSecure && envIsInsecure) {
        console.error('[realtime] Refusing to use insecure VITE_API_URL on https page');
        addToast(
          'error',
          'Insecure VITE_API_URL protocol detected (http/ws). Automatically switched to same-origin WSS. Please check your environment configuration.',
        );
        wsBase = `${proto}//${window.location.host}`;
      } else {
        wsBase = envUrl.replace(/^http/i, 'ws');
      }
    } else {
      wsBase = `${proto}//${window.location.host}`;
    }
    const c = createRealtimeClient({ url: `${wsBase}/ws/orders` });
    clientRef.current = c;
    setClient(c);

    c.onStatus((s) => {
      const isConnected = s === 'connected';
      setStreamConnected(isConnected);
      if (isConnected) {
        setStreamEverConnected(true);
      }
    });

    c.connect();

    // Visibility-aware reconnect: when the tab returns to foreground and we
    // are not connected, force an immediate reconnect attempt instead of
    // waiting for the exponential backoff timer.
    const handleVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const rt = clientRef.current;
      if (rt && !rt.connected) {
        rt.forceReconnect();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      c.disconnect();
      clientRef.current = null;
      setClient(null);
    };
  }, [addToast]);

  return (
    <RealtimeContext.Provider value={{ client, streamConnected, streamEverConnected }}>
      {children}
    </RealtimeContext.Provider>
  );
}