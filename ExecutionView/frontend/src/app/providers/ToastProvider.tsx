// Toast notification context — decouples toast state from UI layout
import { createContext, useContext, useState, useCallback, type ReactNode } from 'react';
import type { Toast } from '@shared/types';

interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: Toast['type'], message: string) => void;
  removeToast: (id: string) => void;
  droppedToastCount: number;
  clearDroppedToastCount: () => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

const MAX_TOASTS = 5;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [droppedToastCount, setDroppedToastCount] = useState(0);

  const addToast = useCallback((type: Toast['type'], message: string) => {
    const id =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    setToasts(prev => {
      const next = [...prev, { id, type, message }];
      if (next.length > MAX_TOASTS) {
        setDroppedToastCount(c => c + (next.length - MAX_TOASTS));
        return next.slice(next.length - MAX_TOASTS);
      }
      return next;
    });
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const clearDroppedToastCount = useCallback(() => setDroppedToastCount(0), []);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast, droppedToastCount, clearDroppedToastCount }}>
      {children}
    </ToastContext.Provider>
  );
}