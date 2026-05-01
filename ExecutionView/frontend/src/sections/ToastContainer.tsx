import { useEffect } from 'react';
import { CheckCircle2, XCircle, Info, X } from 'lucide-react';
import type { Toast } from '@/types';

interface ToastContainerProps {
  toasts: Toast[];
  onRemove: (id: string) => void;
  /** Number of toasts dropped due to the visible-cap. Surfaced as a
   *  "+N more" pill so a network outage no longer looks like only 5 errors
   *  happened — the cap previously discarded older toasts silently. */
  droppedCount?: number;
  /** Clears the dropped counter once the user dismisses the pill. */
  onClearDropped?: () => void;
}

export function ToastContainer({ toasts, onRemove, droppedCount = 0, onClearDropped }: ToastContainerProps) {
  return (
    // pointer-events-none on the wrapper prevents the toast column from
    // capturing clicks across the full bottom-right region (which previously
    // could occlude the footer connection text on small screens).
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-[min(420px,calc(100vw-2rem))] pointer-events-none">
      {droppedCount > 0 && (
        <button
          type="button"
          onClick={onClearDropped}
          className="self-end pointer-events-auto rounded-full bg-amber-500/90 text-black text-xs font-semibold px-3 py-1 shadow-md hover:bg-amber-500"
          title="忽略折叠的提示"
        >
          + {droppedCount} 条更早提示已折叠
        </button>
      )}
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <ToastItem toast={toast} onRemove={onRemove} />
        </div>
      ))}
    </div>
  );
}

interface ToastItemProps {
  toast: Toast;
  onRemove: (id: string) => void;
}

function ToastItem({ toast, onRemove }: ToastItemProps) {
  useEffect(() => {
    const timer = setTimeout(() => {
      onRemove(toast.id);
    }, toast.duration || 5000);

    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onRemove]);

  const getIcon = () => {
    switch (toast.type) {
      case 'success':
        return <CheckCircle2 className="h-5 w-5 shrink-0" />;
      case 'error':
        return <XCircle className="h-5 w-5 shrink-0" />;
      default:
        return <Info className="h-5 w-5 shrink-0" />;
    }
  };

  const getClassName = () => {
    switch (toast.type) {
      case 'success':
        return 'toast-success';
      case 'error':
        return 'toast-error';
      default:
        return 'toast-info';
    }
  };

  // Errors must use `assertive` so screen readers interrupt to read them;
  // info/success use `polite` to avoid stomping on the user's current focus.
  const isError = toast.type === 'error';

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg min-w-[300px] animate-in slide-in-from-right-full ${getClassName()}`}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? 'assertive' : 'polite'}
    >
      {getIcon()}
      {/* break-words + line-clamp prevents long backend stack traces from
          ballooning the toast off-screen. The full message remains in the
          tooltip for users who need to inspect it. */}
      <span
        className="flex-1 text-sm font-medium break-words whitespace-pre-wrap line-clamp-6"
        title={toast.message}
      >
        {toast.message}
      </span>
      <button
        onClick={() => onRemove(toast.id)}
        className="opacity-70 hover:opacity-100 transition-opacity shrink-0"
        aria-label="关闭通知"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
