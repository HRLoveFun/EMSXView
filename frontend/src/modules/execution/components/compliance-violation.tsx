/**
 * Compliance violation badges & tooltip — shared between batch route /
 * batch modify dialogs. Maps backend violation codes to localized labels.
 */

import { AlertTriangle } from 'lucide-react';
import type { Violation, ViolationCode } from '@execution/types'

const VIOLATION_LABELS: Record<ViolationCode, string> = {
  NOTIONAL_TOO_SMALL: 'Notional below USD 10K (soft constraint)',
  NOTIONAL_TOO_LARGE: 'Notional above USD 49M',
  JP_ODD_LOT: 'JP odd lot',
  NOTIONAL_UNKNOWN: 'Cannot estimate notional (last price missing)',
};

// 与组件同文件导出工具函数会牺牲 fast refresh，属可接受取舍
// eslint-disable-next-line react-refresh/only-export-components
export function violationLabel(code: ViolationCode): string {
  return VIOLATION_LABELS[code] ?? code;
}

interface ViolationBadgeProps {
  code: ViolationCode;
  severity?: 'BLOCK' | 'WARN';
  className?: string;
}

function ViolationBadge({ code, severity = 'BLOCK', className = '' }: ViolationBadgeProps) {
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

