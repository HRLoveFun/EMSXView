/**
 * BatchOperationDialogs — confirmation + apply dialogs for multi-route actions.
 *
 * Batch Cancel:   single confirmation covering N routes; submits one CancelRouteEx per route.
 * Batch Modify:  restricted "common delta" editor — a user can change Qty / Order Type +
 *                Price + TIF / Notes, which are then applied identically to all selected
 *                routes via one ModifyRouteEx per route. Strategy parameter editing is
 *                offered only when ALL selected routes share the same (broker, strategy)
 *                pair; in mixed pools the strategy panel is hidden with a warning.
 *                Submission goes through POST /api/routes/batch-modify (dry-run +
 *                NDJSON stream) so server-side compliance can hard-block bad rows.
 */

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2, CheckCircle2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { apiService } from '@/services/api';
import {
  BrokerStrategyFields,
  useStrategyFields,
} from '@/components/broker-strategy-fields';
import { ViolationList } from '@/components/compliance-violation';
import type {
  Route,
  CancelRouteRequest,
  BatchModifyRouteRequest,
  BatchModifyRouteItem,
  BatchOperationItemResult,
  BatchOperationResult,
  Violation,
} from '@/types';

interface OrderTypeOption { value: string; label: string; needsLimit: boolean; needsStop: boolean }
interface TifOption { value: string; label: string }

// ---------- Batch Cancel ----------

interface BatchCancelDialogProps {
  routes: Route[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (req: CancelRouteRequest) => Promise<void>;
  onComplete?: () => void;
  onEachSubmitted?: (route: Route) => void;
}

export function BatchCancelDialog({
  routes, open, onOpenChange, onSubmit, onComplete, onEachSubmitted,
}: BatchCancelDialogProps) {
  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errors, setErrors] = useState<{ route: Route; message: string }[]>([]);

  useEffect(() => {
    if (open) { setProgress(0); setErrors([]); }
  }, [open]);

  const run = async () => {
    setSubmitting(true);
    setProgress(0);
    setErrors([]);
    const failures: { route: Route; message: string }[] = [];
    for (let i = 0; i < routes.length; i++) {
      const r = routes[i];
      try {
        await onSubmit({ sequence: r.sequence, routeId: r.routeId });
        onEachSubmitted?.(r);
      } catch (err) {
        failures.push({ route: r, message: err instanceof Error ? err.message : String(err) });
      }
      setProgress(i + 1);
    }
    setErrors(failures);
    setSubmitting(false);
    if (failures.length === 0) {
      onComplete?.();
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!submitting) onOpenChange(v); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Cancel {routes.length} route{routes.length === 1 ? '' : 's'}?</DialogTitle>
          <DialogDescription>
            A separate CancelRouteEx request will be submitted for each selected route.
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-64 overflow-y-auto border border-border rounded">
          <table className="w-full text-xs">
            <thead className="bg-secondary/50">
              <tr>
                <th className="text-left px-2 py-1">Route</th>
                <th className="text-left px-2 py-1">Ticker</th>
                <th className="text-left px-2 py-1">Broker</th>
                <th className="text-right px-2 py-1">Qty</th>
                <th className="text-left px-2 py-1">Status</th>
              </tr>
            </thead>
            <tbody>
              {routes.map(r => (
                <tr key={r.id} className="border-t border-border/50">
                  <td className="px-2 py-0.5 font-mono">{r.sequence}.{r.routeId}</td>
                  <td className="px-2 py-0.5">{r.ticker || '-'}</td>
                  <td className="px-2 py-0.5 font-mono">{r.broker}</td>
                  <td className="px-2 py-0.5 text-right font-mono-numbers">{r.amount}</td>
                  <td className="px-2 py-0.5">{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {submitting && (
          <p className="text-xs text-muted-foreground">
            Submitting {progress} / {routes.length}…
          </p>
        )}
        {errors.length > 0 && (
          <div className="text-xs text-destructive space-y-1">
            <p className="flex items-center gap-1"><AlertTriangle className="h-3 w-3" />{errors.length} request(s) failed:</p>
            {errors.slice(0, 5).map((e, i) => (
              <p key={i} className="font-mono">  {e.route.sequence}.{e.route.routeId}: {e.message}</p>
            ))}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>Close</Button>
          <Button variant="destructive" onClick={run} disabled={submitting || routes.length === 0}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Cancel {routes.length} route{routes.length === 1 ? '' : 's'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------- Batch Modify ----------

interface BatchModifyDialogProps {
  routes: Route[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Notified after each route's per-item NDJSON line lands (any status). */
  onEachSubmitted?: (route: Route, status: 'SUCCESS' | 'BLOCKED' | 'FAILED') => void;
  onComplete?: () => void;
}

type Phase = 'configure' | 'review' | 'submitting' | 'result';

export function BatchModifyDialog({
  routes, open, onOpenChange, onEachSubmitted, onComplete,
}: BatchModifyDialogProps) {
  const [orderTypes, setOrderTypes] = useState<OrderTypeOption[]>([]);
  const [tifOptions, setTifOptions] = useState<TifOption[]>([]);

  // Editable deltas — blank means "unchanged" for that route.
  const [newQty, setNewQty] = useState('');
  const [newOrderType, setNewOrderType] = useState('');
  const [newLimitPrice, setNewLimitPrice] = useState('');
  const [newStopPrice, setNewStopPrice] = useState('');
  const [newTif, setNewTif] = useState('');
  const [newNotes, setNewNotes] = useState('');
  const [notesDirty, setNotesDirty] = useState(false);

  const [phase, setPhase] = useState<Phase>('configure');
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState('');
  const [perRoute, setPerRoute] = useState<Record<string, { status?: 'SUCCESS' | 'BLOCKED' | 'FAILED'; message?: string; violations: Violation[] }>>({});
  const [summary, setSummary] = useState<BatchOperationResult | null>(null);

  // Detect a common (broker, strategyType) — strategy params are only safe
  // to edit collectively when this is uniform across all selected routes.
  const commonBrokerStrategy = useMemo(() => {
    if (routes.length === 0) return null;
    const first = { broker: routes[0].broker, strategy: routes[0].strategyType };
    if (!first.broker || !first.strategy) return null;
    const allMatch = routes.every(r => r.broker === first.broker && r.strategyType === first.strategy);
    return allMatch ? first : null;
  }, [routes]);

  const strategyFields = useStrategyFields(
    commonBrokerStrategy?.broker ?? '',
    commonBrokerStrategy?.strategy ?? '',
    'EQTY',
  );

  // Load enums once per mount
  useEffect(() => {
    apiService.getRouteEnums().then(res => {
      if (res.success && res.data) {
        setOrderTypes(res.data.orderTypes);
        setTifOptions(res.data.tifOptions);
      }
    }).catch(() => { /* ignore */ });
  }, []);

  // Reset on open
  useEffect(() => {
    if (open) {
      setNewQty(''); setNewOrderType(''); setNewLimitPrice('');
      setNewStopPrice(''); setNewTif(''); setNewNotes(''); setNotesDirty(false);
      setProgress(0); setErrorMsg(''); setPerRoute({}); setSummary(null);
      setPhase('configure');
    }
  }, [open]);

  const currentOrderType = useMemo(
    () => orderTypes.find(o => o.value === newOrderType),
    [orderTypes, newOrderType],
  );

  // Summary of current uniformity per field — helps user know what they're overwriting.
  const uniform = useMemo(() => {
    const single = <K extends keyof Route>(k: K): Route[K] | null => {
      if (routes.length === 0) return null;
      const first = routes[0][k];
      return routes.every(r => r[k] === first) ? first : null;
    };
    return {
      orderType: single('orderType'),
      tif: single('tif'),
      broker: single('broker'),
      strategy: single('strategyType'),
    };
  }, [routes]);

  const dirtyFieldCount =
    (newQty !== '' ? 1 : 0) +
    (newOrderType !== '' ? 1 : 0) +
    (newLimitPrice !== '' ? 1 : 0) +
    (newStopPrice !== '' ? 1 : 0) +
    (newTif !== '' ? 1 : 0) +
    (notesDirty ? 1 : 0) +
    (commonBrokerStrategy && strategyFields.dirty ? 1 : 0);

  // Build the BatchModifyRouteRequest based on the current delta form.
  const buildRequest = (dryRun: boolean): BatchModifyRouteRequest => {
    const template: BatchModifyRouteRequest['template'] = {};
    if (newQty !== '') {
      const q = parseInt(newQty, 10);
      if (Number.isFinite(q)) template.amount = q;
    }
    if (newOrderType !== '') {
      template.orderType = newOrderType;
      const tifValue = newTif !== '' ? newTif : 'DAY';
      template.tif = tifValue;
      const needsLimit = currentOrderType?.needsLimit ?? false;
      const needsStop = currentOrderType?.needsStop ?? false;
      template.limitPrice = needsLimit
        ? (newLimitPrice !== '' ? parseFloat(newLimitPrice) : null)
        : null;
      template.stopPrice = needsStop
        ? (newStopPrice !== '' ? parseFloat(newStopPrice) : null)
        : null;
    } else {
      if (newLimitPrice !== '') template.limitPrice = parseFloat(newLimitPrice);
      if (newStopPrice !== '') template.stopPrice = parseFloat(newStopPrice);
      if (newTif !== '') template.tif = newTif;
    }
    if (notesDirty) template.notes = newNotes;
    if (commonBrokerStrategy && strategyFields.dirty) {
      const sp = strategyFields.toStrategyParams(commonBrokerStrategy.strategy);
      if (sp) template.strategyParams = sp;
    }
    const items: BatchModifyRouteItem[] = routes.map(r => ({
      sequence: r.sequence,
      routeId: r.routeId,
    }));
    return { template, items, dryRun };
  };

  const runValidate = async () => {
    if (dirtyFieldCount === 0) return;

    // Local sanity: qty must be positive and not below filled.
    if (newQty !== '') {
      const q = parseInt(newQty, 10);
      if (!Number.isFinite(q) || q <= 0) {
        setErrorMsg('Quantity must be a positive integer');
        return;
      }
      const offending = routes.find(r => q < r.filled);
      if (offending) {
        setErrorMsg(`Target qty ${q} below filled qty for ${offending.sequence}.${offending.routeId} (${offending.filled})`);
        return;
      }
    }

    setErrorMsg('');
    setPhase('submitting');
    const res = await apiService.dryRunBatchModifyRoutes(buildRequest(true));
    if (!res.success || !res.data) {
      setErrorMsg(res.error || 'Validation failed');
      setPhase('configure');
      return;
    }
    const map: typeof perRoute = {};
    for (const item of res.data.items) {
      map[item.key] = {
        violations: item.violations,
        status: item.status === 'BLOCKED' ? 'BLOCKED' : undefined,
      };
    }
    setPerRoute(map);
    setSummary(res.data);
    setPhase('review');
  };

  const runSubmit = async () => {
    setErrorMsg('');
    setPhase('submitting');
    setProgress(0);
    let count = 0;
    const res = await apiService.streamBatchModifyRoutes(
      buildRequest(false),
      (item: BatchOperationItemResult) => {
        count += 1;
        setProgress(count);
        setPerRoute(prev => ({
          ...prev,
          [item.key]: {
            status: item.status,
            message: item.message,
            violations: item.violations,
          },
        }));
        const route = routes.find(r => `${r.sequence}.${r.routeId}` === item.key);
        if (route) onEachSubmitted?.(route, item.status);
      },
      (s: BatchOperationResult) => setSummary(s),
    );
    if (!res.success) setErrorMsg(res.error || 'Submission failed');
    setPhase('result');
    if (summary && summary.failed === 0 && summary.blocked === 0) onComplete?.();
  };

  const close = () => {
    if (phase === 'submitting') return;
    if (phase === 'result') onComplete?.();
    onOpenChange(false);
  };

  const formDisabled = phase === 'submitting' || phase === 'result';

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) close(); }}>
      <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Batch Modify — {routes.length} route{routes.length === 1 ? '' : 's'}</DialogTitle>
          <DialogDescription>
            Common delta editor. Leave a field blank to keep each route's current value.
            Server-side compliance (USD &lt; 10K / &gt; 49M, JP odd lot) hard-blocks unsafe rows.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* Uniformity badges */}
          <div className="flex flex-wrap gap-1 text-[11px]">
            <UniformBadge label="Order Type" value={uniform.orderType} />
            <UniformBadge label="TIF" value={uniform.tif} />
            <UniformBadge label="Broker" value={uniform.broker} />
            <UniformBadge label="Strategy" value={uniform.strategy ?? null} />
          </div>

          {/* Delta fields */}
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-xs">New Qty</Label>
              <Input type="number" value={newQty} onChange={(e) => setNewQty(e.target.value)}
                placeholder="unchanged" className="h-8 font-mono" disabled={formDisabled} />
            </div>
            <div>
              <Label className="text-xs">New Order Type</Label>
              <Select value={newOrderType || '__none__'} onValueChange={(v) => setNewOrderType(v === '__none__' ? '' : v)} disabled={formDisabled}>
                <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">(unchanged)</SelectItem>
                  {orderTypes.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">New TIF</Label>
              <Select value={newTif || '__none__'} onValueChange={(v) => setNewTif(v === '__none__' ? '' : v)} disabled={formDisabled}>
                <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">(unchanged)</SelectItem>
                  {tifOptions.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">New Limit Price</Label>
              <Input type="number" step="0.01" value={newLimitPrice}
                onChange={(e) => setNewLimitPrice(e.target.value)}
                placeholder="unchanged" className="h-8 font-mono" disabled={formDisabled} />
            </div>
            <div>
              <Label className="text-xs">New Stop Price</Label>
              <Input type="number" step="0.01" value={newStopPrice}
                onChange={(e) => setNewStopPrice(e.target.value)}
                placeholder="unchanged" className="h-8 font-mono" disabled={formDisabled} />
            </div>
            <div>
              <Label className="text-xs">New Notes {notesDirty && <span className="text-amber-600">●</span>}</Label>
              <Input value={newNotes}
                onChange={(e) => { setNewNotes(e.target.value); setNotesDirty(true); }}
                placeholder="(leave blank + don't type to skip)" className="h-8" disabled={formDisabled} />
            </div>
          </div>

          {/* Strategy params — only when broker + strategy are uniform */}
          {commonBrokerStrategy ? (
            <BrokerStrategyFields
              fields={strategyFields.fields}
              setFields={strategyFields.setFields}
              isLoading={strategyFields.isLoading}
              title={`Strategy Params — ${commonBrokerStrategy.broker} / ${commonBrokerStrategy.strategy}`}
              caption="Applied to every selected route"
              hideWhenEmpty
            />
          ) : (
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Mixed broker / strategy across selected routes — strategy parameter editing
                is disabled. Edit strategy parameters per-route from the row menu.
              </AlertDescription>
            </Alert>
          )}

          {/* Target routes table */}
          <div className="max-h-48 overflow-y-auto border border-border rounded text-xs">
            <table className="w-full">
              <thead className="bg-secondary/50">
                <tr>
                  <th className="text-left px-2 py-1">Route</th>
                  <th className="text-left px-2 py-1">Ticker</th>
                  <th className="text-left px-2 py-1">Broker</th>
                  <th className="text-right px-2 py-1">Qty → Filled</th>
                  <th className="text-left px-2 py-1">Type / TIF</th>
                  <th className="text-left px-2 py-1">Status</th>
                </tr>
              </thead>
              <tbody>
                {routes.map(r => {
                  const key = `${r.sequence}.${r.routeId}`;
                  const pr = perRoute[key];
                  return (
                    <tr key={r.id}
                      className={
                        'border-t border-border/50 ' +
                        (pr?.status === 'BLOCKED' ? 'bg-red-500/5 ' : '') +
                        (pr?.status === 'SUCCESS' ? 'bg-emerald-500/5 ' : '') +
                        (pr?.status === 'FAILED' ? 'bg-amber-500/5 ' : '')
                      }
                    >
                      <td className="px-2 py-0.5 font-mono">{key}</td>
                      <td className="px-2 py-0.5">{r.ticker || '-'}</td>
                      <td className="px-2 py-0.5 font-mono">{r.broker}</td>
                      <td className="px-2 py-0.5 text-right font-mono-numbers">{r.amount} → {r.filled}</td>
                      <td className="px-2 py-0.5">{r.orderType || '-'} / {r.tif || '-'}</td>
                      <td className="px-2 py-0.5">
                        {pr?.status === 'SUCCESS' && <span className="text-emerald-600 inline-flex items-center gap-1"><CheckCircle2 className="h-3 w-3" />Modified</span>}
                        {pr?.status === 'BLOCKED' && <ViolationList violations={pr.violations} />}
                        {pr?.status === 'FAILED' && <span className="text-amber-600">{pr.message}</span>}
                        {!pr?.status && (pr?.violations?.length ?? 0) > 0 && <ViolationList violations={pr!.violations} />}
                        {!pr && r.status}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {phase === 'submitting' && <p className="text-xs text-muted-foreground">Working… {progress > 0 ? `${progress} / ${routes.length}` : ''}</p>}

          {errorMsg && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{errorMsg}</AlertDescription>
            </Alert>
          )}
          {phase === 'result' && summary && (
            <Alert>
              <AlertDescription>
                <strong>Done.</strong> Total {summary.total} ·
                <span className="text-emerald-600"> {summary.succeeded} succeeded</span> ·
                <span className="text-red-600"> {summary.blocked} blocked</span> ·
                <span className="text-amber-600"> {summary.failed} failed</span>
              </AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          {phase === 'configure' && (
            <>
              <Button variant="outline" onClick={close}>Cancel</Button>
              <Button onClick={runValidate} disabled={dirtyFieldCount === 0 || routes.length === 0}>
                Validate ({dirtyFieldCount} field{dirtyFieldCount === 1 ? '' : 's'})
              </Button>
            </>
          )}
          {phase === 'review' && (
            <>
              <Button variant="outline" onClick={() => setPhase('configure')}>Back</Button>
              <Button onClick={runSubmit}>
                Confirm &amp; Apply to {routes.length} route{routes.length === 1 ? '' : 's'}
              </Button>
            </>
          )}
          {phase === 'submitting' && (
            <Button disabled><Loader2 className="mr-2 h-4 w-4 animate-spin" />Working…</Button>
          )}
          {phase === 'result' && <Button onClick={close}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UniformBadge({ label, value }: { label: string; value: string | number | null }) {
  if (value === null || value === '' || value === undefined) {
    return (
      <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-300 border border-amber-500/30">
        {label}: mixed
      </span>
    );
  }
  return (
    <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">
      {label}: {String(value)}
    </span>
  );
}
