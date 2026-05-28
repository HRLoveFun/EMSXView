/**
 * Compliance violation badges & tooltip — shared between batch route /
 * batch modify dialogs. Maps backend violation codes to localized labels.
 */

import { AlertTriangle } from 'lucide-react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { Violation, ViolationCode } from '@execution/types'

const VIOLATION_LABELS: Record<ViolationCode, string> = {
  NOTIONAL_TOO_SMALL: 'Notional below USD 10K (soft constraint)',
  NOTIONAL_TOO_LARGE: 'Notional above USD 49M',
  JP_ODD_LOT: 'JP odd lot',
  NOTIONAL_UNKNOWN: 'Cannot estimate notional (last price missing)',
};

export function violationLabel(code: ViolationCode): string {
  return VIOLATION_LABELS[code] ?? code;
}

interface ViolationBadgeProps {
  code: ViolationCode;
  severity?: 'BLOCK' | 'WARN';
  className?: string;
}

export function ViolationBadge({ code, severity = 'BLOCK', className = '' }: ViolationBadgeProps) {
  const isWarn = severity === 'WARN';
  return (
    <span
      className={
        'inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] ' +
        (isWarn
          ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/40'
          : 'bg-red-500/15 text-red-700 dark:text-red-300 border border-red-500/40') +
        ' ' + className
      }
    >
      <AlertTriangle className="h-3 w-3" />
      {violationLabel(code)}
    </span>
  );
}

interface ViolationListProps {
  violations: Violation[];
  className?: string;
}

/** Inline list of badges — one per violation. */
export function ViolationList({ violations, className = '' }: ViolationListProps) {
  if (!violations.length) return null;
  return (
    <div className={`flex flex-wrap gap-1 ${className}`}>
      {violations.map((v, i) => (
        <ViolationBadge key={`${v.code}-${i}`} code={v.code} severity={v.severity} />
      ))}
    </div>
  );
}

interface ViolationTooltipProps {
  violations: Violation[];
  children: React.ReactNode;
}

/** Hover tooltip showing full violation messages, used on table cells. */
export function ViolationTooltip({ violations, children }: ViolationTooltipProps) {
  if (!violations.length) return <>{children}</>;
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-block">{children}</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <ul className="space-y-1 text-xs">
            {violations.map((v, i) => (
              <li key={i}>
                <span className="font-semibold">{violationLabel(v.code)}</span>
                <span className="text-muted-foreground"> — {typeof v.message === 'string' ? v.message : JSON.stringify(v.message)}</span>
              </li>
            ))}
          </ul>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}