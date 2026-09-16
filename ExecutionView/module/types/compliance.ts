/**
 * Pre-trade compliance types.
 *
 * P3-SRP: Extracted from types/index.ts.
 */

export type ViolationCode =
  | 'NOTIONAL_TOO_SMALL'
  | 'NOTIONAL_TOO_LARGE'
  | 'JP_ODD_LOT'
  | 'NOTIONAL_UNKNOWN';

export interface Violation {
  code: ViolationCode;
  message: string;
  severity: 'BLOCK' | 'WARN';
  details?: Record<string, unknown> | null;
}
