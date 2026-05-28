import { useState, useEffect, useCallback } from 'react';
import { SlidersHorizontal, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  CONDITION_DEFS,
  DEFAULT_CONDITIONS,
  type MonitorConditions,
  type ConditionConfig,
  type BoolConditionConfig,
} from '@execution/lib/monitor-conditions';

interface MonitorConditionsSectionProps {
  monitorConditions?: MonitorConditions;
  onMonitorConditionsChange?: (c: MonitorConditions) => void;
}

export function MonitorConditionsSection({ monitorConditions, onMonitorConditionsChange }: MonitorConditionsSectionProps) {
  const [savedFlashAt, setSavedFlashAt] = useState<number | null>(null);

  const handleConditionsChange = useCallback((next: MonitorConditions) => {
    if (!onMonitorConditionsChange) return;
    onMonitorConditionsChange(next);
    setSavedFlashAt(Date.now());
  }, [onMonitorConditionsChange]);

  useEffect(() => {
    if (!savedFlashAt) return;
    const t = setTimeout(() => setSavedFlashAt(null), 1500);
    return () => clearTimeout(t);
  }, [savedFlashAt]);

  if (!monitorConditions || !onMonitorConditionsChange) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Monitor Conditions</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>Monitor conditions wiring unavailable.</AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Monitor Conditions</CardTitle>
          </div>
          {savedFlashAt && (
            <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium animate-in fade-in" role="status" aria-live="polite">
              ✓ Saved
            </span>
          )}
        </div>
        <CardDescription>Configure threshold triggers that flag orders on the Monitor Board. Changes apply immediately.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 gap-2">
          {CONDITION_DEFS.map((def) => {
            const cfg = monitorConditions[def.id];
            const isDollar = def.id === 'dollarValueLow' || def.id === 'dollarValueHigh';
            const isBool = def.isBool;
            const setField = (patch: Partial<ConditionConfig & BoolConditionConfig>) => {
              handleConditionsChange({
                ...monitorConditions,
                [def.id]: { ...cfg, ...patch },
              } as MonitorConditions);
            };
            return (
              <div key={def.id} className={`flex items-center gap-3 px-3 py-2 rounded-md border border-border ${cfg.enabled ? '' : 'opacity-60'}`}>
                <Checkbox checked={cfg.enabled} onCheckedChange={(v) => setField({ enabled: Boolean(v) })} />
                <div className="flex-1">
                  <div className="text-sm font-medium">{def.label} {def.unit}</div>
                  <div className="text-[11px] text-muted-foreground">runtime-evaluated on Monitor Board</div>
                </div>
                {isBool ? (
                  <Select value={String((cfg as BoolConditionConfig).value)} onValueChange={(v) => setField({ value: v === 'true' })} disabled={!cfg.enabled}>
                    <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="true">Yes</SelectItem>
                      <SelectItem value="false">No</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <Input type="number" value={(cfg as ConditionConfig).threshold} onChange={(e) => setField({ threshold: parseFloat(e.target.value) || 0 })} step={isDollar ? 1000 : 0.5} className="h-8 w-32 text-right font-mono" disabled={!cfg.enabled} />
                )}
              </div>
            );
          })}

          {(() => {
            const lazyCfg = monitorConditions.lazy;
            return (
              <div key="lazy" className={`flex items-center gap-3 px-3 py-2 rounded-md border border-border ${lazyCfg.enabled ? '' : 'opacity-60'}`}>
                <Checkbox checked={lazyCfg.enabled} onCheckedChange={(v) => handleConditionsChange({ ...monitorConditions, lazy: { ...lazyCfg, enabled: Boolean(v) } })} />
                <div className="flex-1">
                  <div className="text-sm font-medium">Lazy Order</div>
                  <div className="text-[11px] text-muted-foreground">Status not in {'{'}WORKING, QUEUED, COMPLETED, FILLED, SUSPENDED{'}'} or idle share &gt; 0</div>
                </div>
                <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-100 text-sky-700">Lazy</span>
              </div>
            );
          })()}
        </div>

        <div className="border-t border-border pt-3 flex items-center justify-between">
          <div className="text-xs text-muted-foreground">
            System rules (always on):
            <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700 mr-1">Critical</span>
          </div>
          <Button variant="ghost" size="sm" onClick={() => handleConditionsChange(structuredClone(DEFAULT_CONDITIONS))}>
            <RefreshCw className="h-3 w-3 mr-1" />Reset to defaults
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
