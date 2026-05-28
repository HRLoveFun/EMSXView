/**
 * BrokerStrategyFields — shared editable strategy-parameter panel.
 *
 * Used by Modify-Route and Route-Order dialogs to keep their strategy
 * parameter editing UX in lockstep. The parent owns the field state via
 * `useStrategyFields(...)`; this component is purely presentational.
 *
 * Backend payload contract
 *   `toStrategyParams()` produces a `{ strategyName, fields: [{value, disabled}] }`
 *   object accepted by both `RouteOrderRequest.strategyParams` and
 *   `ModifyRouteRequest.strategyParams` (see route_service.build_strategy_elements).
 */

import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { cachedApiService } from '@execution/services/execution-api';
import type { BrokerStrategyField } from '@execution/types'

export interface StrategyFieldState {
  fieldName: string;
  value: string;
  disabled: boolean;
  defaultValue: string;
  originalValue: string;
  originalDisabled: boolean;
}

export interface UseStrategyFieldsResult {
  fields: StrategyFieldState[];
  setFields: React.Dispatch<React.SetStateAction<StrategyFieldState[]>>;
  isLoading: boolean;
  /** Force a refetch (bypasses the LocalStorage cache). */
  refresh: () => Promise<void>;
  /** True when any field's value or disabled flag differs from its baseline. */
  dirty: boolean;
  /** Build the payload for `RouteOrderRequest.strategyParams` /
   *  `ModifyRouteRequest.strategyParams`. Returns `null` when no strategy
   *  is selected or no fields are loaded. */
  toStrategyParams: (strategyName: string) => {
    strategyName: string;
    fields: Array<{ value: string; disabled: boolean }>;
  } | null;
}

/** Hook: load and manage broker-strategy field state.
 *
 *  When `broker` or `strategy` is empty, the field list is cleared. When both
 *  are present, the hook fetches the field metadata via
 *  `cachedApiService.getBrokerStrategyInfo` and seeds editable state.
 */
export function useStrategyFields(
  broker: string,
  strategy: string,
  assetClass: string,
): UseStrategyFieldsResult {
  const [fields, setFields] = useState<StrategyFieldState[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const load = useCallback(async (force: boolean) => {
    if (!broker || !strategy) {
      setFields([]);
      return;
    }
    setIsLoading(true);
    try {
      const res = await cachedApiService.getBrokerStrategyInfo(broker, strategy, assetClass, force);
      if (res.success && res.data) {
        setFields(res.data.fields.map((f: BrokerStrategyField) => {
          const value = f.stringValue || '';
          const disabled = f.disable === '1';
          return {
            fieldName: f.fieldName,
            value,
            disabled,
            defaultValue: value,
            originalValue: value,
            originalDisabled: disabled,
          };
        }));
      } else {
        setFields([]);
      }
    } finally {
      setIsLoading(false);
    }
  }, [broker, strategy, assetClass]);

  useEffect(() => { void load(false); }, [load]);

  const refresh = useCallback(() => load(true), [load]);

  const dirty = fields.some(f => f.value !== f.originalValue || f.disabled !== f.originalDisabled);

  const toStrategyParams = useCallback(
    (strategyName: string) => {
      if (!strategyName || fields.length === 0) return null;
      return {
        strategyName,
        fields: fields.map(f => ({ value: f.value, disabled: f.disabled })),
      };
    },
    [fields],
  );

  return { fields, setFields, isLoading, refresh, dirty, toStrategyParams };
}

// ─────────────────────────────────────────────────────────────────────────────

interface BrokerStrategyFieldsProps {
  fields: StrategyFieldState[];
  setFields: React.Dispatch<React.SetStateAction<StrategyFieldState[]>>;
  isLoading: boolean;
  /** Title shown above the grid (default "Strat Params"). */
  title?: string;
  /** Explanatory caption shown next to the title. */
  caption?: string;
  /** When true, the editor takes no vertical space when there's nothing to show. */
  hideWhenEmpty?: boolean;
}

/** Returns the amber highlight class when dirty, otherwise empty. */
function dirtyClass(dirty: boolean): string {
  return dirty
    ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-500/60 text-amber-900 dark:text-amber-100'
    : '';
}

export function BrokerStrategyFields({
  fields,
  setFields,
  isLoading,
  title = 'Strat Params',
  caption = 'Toggle "Off" to skip a field (Bloomberg EMSX_FIELD_INDICATOR=1)',
  hideWhenEmpty = false,
}: BrokerStrategyFieldsProps) {
  if (hideWhenEmpty && !isLoading && fields.length === 0) return null;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Label className="text-xs font-medium">{title}</Label>
        <span className="text-[10px] text-muted-foreground">{caption}</span>
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Loading parameters…
        </div>
      ) : fields.length > 0 ? (
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 max-h-56 overflow-y-auto pr-1 border border-border rounded p-2">
          {fields.map((field, idx) => {
            const fieldDirty =
              field.value !== field.originalValue || field.disabled !== field.originalDisabled;
            return (
              <div key={field.fieldName} className="flex items-center gap-1">
                <label
                  className="w-24 text-[11px] text-muted-foreground truncate"
                  title={field.fieldName}
                >
                  {field.fieldName}
                </label>
                <Input
                  value={field.disabled ? '' : field.value}
                  onChange={(e) => {
                    const v = e.target.value;
                    setFields(prev => {
                      const next = [...prev];
                      next[idx] = { ...next[idx], value: v, disabled: false };
                      return next;
                    });
                  }}
                  disabled={field.disabled}
                  placeholder={field.disabled ? '(off)' : ''}
                  className={`h-6 text-xs flex-1 font-mono ${dirtyClass(fieldDirty)}`}
                />
                <button
                  type="button"
                  onClick={() =>
                    setFields(prev => {
                      const next = [...prev];
                      next[idx] = { ...next[idx], disabled: !next[idx].disabled };
                      return next;
                    })
                  }
                  className={`text-[10px] px-1.5 py-0.5 rounded border ${
                    field.disabled
                      ? 'bg-muted text-muted-foreground border-border'
                      : 'bg-primary/10 text-primary border-primary/30'
                  }`}
                >
                  {field.disabled ? 'Off' : 'On'}
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No parameters for this strategy</p>
      )}
    </div>
  );
}