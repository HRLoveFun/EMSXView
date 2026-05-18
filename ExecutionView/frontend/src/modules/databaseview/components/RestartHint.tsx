import { useState } from 'react';
import { Info, ChevronDown, ChevronRight } from 'lucide-react';

/**
 * Discoverable, dismissible callout that tells the user how to restart
 * services after a code change. Targeted at non-technical users who do not
 * know what "FastAPI" or "npm run dev" means.
 *
 * Only shown when the page is loaded from localhost (i.e. the developer /
 * researcher running the local stack). Hidden in remote/production loads
 * where the user has no shell access anyway.
 */
export function RestartHint() {
  const [open, setOpen] = useState(false);

  const isLocal =
    typeof window !== 'undefined' &&
    /^(localhost|127\.0\.0\.1|::1)$/.test(window.location.hostname);
  if (!isLocal) return null;

  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-900 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5" />
        )}
        <Info className="h-3.5 w-3.5" />
        <span className="font-medium">See fields or features that don't match the latest code? Click here for help</span>
      </button>

      {open && (
        <div className="mt-2 space-y-2 pl-6 leading-relaxed">
          <p>
            After modifying Python code in the backend (FastAPI), a restart is required for changes to take effect. Frontend code usually hot-reloads automatically, but some changes also require a restart.
          </p>
          <p className="font-medium text-sky-900 dark:text-sky-100">
            Easiest way: double-click{' '}
            <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
              restart-services.bat
            </code>
          </p>
          <ol className="list-decimal space-y-0.5 pl-5 text-[11px]">
            <li>
              Open the folder{' '}
              <code className="font-mono">C:\Users\hrchen\Documents\EMSX</code>
            </li>
            <li>
              Find{' '}
              <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
                restart-services.bat
              </code>{' '}
              file, then <strong>double-click</strong> it
            </li>
            <li>Wait for the black window to show "[Success] Service has been restarted", then the browser will automatically refresh to the frontend page</li>
            <li>
              In the top-right corner of this page, click{' '}
              <code className="rounded bg-sky-100 px-1.5 py-0.5 font-mono dark:bg-sky-900/60">
                Refresh
              </code>{' '}
              to see the latest data
            </li>
          </ol>
          <p className="text-[10px] text-sky-700 dark:text-sky-400">
            Tip: Right-click this .bat file and select{' '}
            <strong>Send to ▸ Desktop shortcut</strong> for one-click restart from your desktop.
          </p>
        </div>
      )}
    </div>
  );
}