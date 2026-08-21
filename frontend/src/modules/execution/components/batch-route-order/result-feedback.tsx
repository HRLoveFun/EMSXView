import { AlertTriangle, Loader2 } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { violationLabel } from '@execution/components/compliance-violation';
import type { ResultFeedbackProps } from './types';

export function ResultFeedback({
  phase,
  error,
  progress,
  summary,
  totalDestinations,
  blockedDetails,
  failedDetails,
  warnDetails,
}: ResultFeedbackProps) {
  return (
    <>
      {/* ── Progress indicator ─────────────────────────────────── */}
      {phase === 'submitting' && (
        <p className="text-xs text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          {summary
            ? `Submitted ${progress} / ${totalDestinations}`
            : 'Validating\u2026'}
        </p>
      )}

      {/* ── Error alert ────────────────────────────────────────── */}
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            <div>{typeof error === 'string' ? error : JSON.stringify(error)}</div>
            {blockedDetails.length > 0 && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer select-none">
                  View {blockedDetails.length} blocked destination
                  {blockedDetails.length === 1 ? '' : 's'}
                </summary>
                <ul className="mt-1 space-y-1 max-h-48 overflow-y-auto pr-1">
                  {blockedDetails.map(d => (
                    <li
                      key={`${d.orderId}#${d.broker}`}
                      className="border-l-2 border-red-500/60 pl-2"
                    >
                      <div className="font-mono">
                        <span className="font-semibold">{d.symbol}</span>
                        <span className="text-muted-foreground"> {'\u00B7'} {d.broker}</span>
                      </div>
                      {d.violations.length === 0 ? (
                        <div className="text-muted-foreground italic">
                          {d.message || '(no violation detail returned)'}
                        </div>
                      ) : (
                        <ul className="ml-2">
                          {d.violations.map((v, i) => (
                            <li key={`${v.code}-${i}`}>
                              <span className="font-semibold">{violationLabel(v.code)}</span>
                              <span className="text-muted-foreground"> {'\u2014'} {typeof v.message === 'string' ? v.message : JSON.stringify(v.message)}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </AlertDescription>
        </Alert>
      )}

      {/* ── Result summary ──────────────────────────────────────── */}
      {phase === 'result' && summary && (
        <Alert>
          <AlertDescription>
            <div>
              <strong>Done.</strong> Total {summary.total} {'\u00B7'}
              <span className="text-emerald-600"> {summary.succeeded} succeeded</span> {'\u00B7'}
              <span className="text-red-600"> {summary.blocked} blocked</span> {'\u00B7'}
              <span className="text-amber-600"> {summary.failed} failed</span>
            </div>
            {failedDetails.length > 0 && (
              <details className="mt-2 text-xs" open>
                <summary className="cursor-pointer select-none">
                  View {failedDetails.length} failed destination
                  {failedDetails.length === 1 ? '' : 's'}
                </summary>
                <ul className="mt-1 space-y-1 max-h-48 overflow-y-auto pr-1">
                  {failedDetails.map(d => (
                    <li
                      key={`${d.orderId}#${d.broker}`}
                      className="border-l-2 border-amber-500/60 pl-2"
                    >
                      <div className="font-mono">
                        <span className="font-semibold">{d.symbol}</span>
                        <span className="text-muted-foreground"> {'\u00B7'} {d.broker}</span>
                      </div>
                      <div className="text-muted-foreground">{typeof d.message === 'string' ? d.message : JSON.stringify(d.message)}</div>
                      {/Invalid Handling Instruction/i.test(typeof d.message === 'string' ? d.message : JSON.stringify(d.message)) && (
                        <div className="text-amber-700 dark:text-amber-300 mt-0.5">
                          Note: This broker code does not have staging permission enabled in the EMSX API.
                          Please contact Bloomberg / broker to enable API
                          authorization before routing.
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {/* Soft-warn violations on successful routes */}
            {warnDetails.length > 0 && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer select-none text-amber-600">
                  {warnDetails.length} destination{warnDetails.length === 1 ? '' : 's'} routed with advisory warning{warnDetails.length === 1 ? '' : 's'}
                </summary>
                <ul className="mt-1 space-y-1 max-h-32 overflow-y-auto pr-1">
                  {warnDetails.map(d => (
                    <li
                      key={`${d.orderId}#${d.broker}-warn`}
                      className="border-l-2 border-amber-400/60 pl-2"
                    >
                      <div className="font-mono">
                        <span className="font-semibold">{d.symbol}</span>
                        <span className="text-muted-foreground"> {'\u00B7'} {d.broker}</span>
                      </div>
                      {d.violations.map((v, i) => (
                        <div key={i} className="text-muted-foreground">
                          {violationLabel(v.code)} {'\u2014'} {typeof v.message === 'string' ? v.message : JSON.stringify(v.message)}
                        </div>
                      ))}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            {failedDetails.length === 0 &&
              blockedDetails.length > 0 &&
              (summary.blocked ?? 0) > 0 && (
                <div className="mt-1 text-xs text-muted-foreground">
                  {blockedDetails.length} blocked {'\u2014'} see banner above for details.
                </div>
              )}
          </AlertDescription>
        </Alert>
      )}
    </>
  );
}
