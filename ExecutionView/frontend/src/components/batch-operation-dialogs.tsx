/**
 * BatchOperationDialogs — confirmation + apply dialogs for multi-route actions.
 *
 * Batch Cancel:   single confirmation covering N routes; submits one CancelRouteEx per route.
 * Batch Modify:  restricted "common delta" editor — a user can change Qty / Order Type +
 *                Price + TIF / Notes, which are then applied identically to all selected
 *                routes via one ModifyRouteEx per route. Broker / Strategy editing is
 *                deliberately disabled in batch mode because strategy parameter schemas
 *                differ per (broker, strategy) pair and must be edited per-route to
 *                remain safe.
 */

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
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
import { apiService } from '@/services/api';
import type { Route, CancelRouteRequest, ModifyRouteRequest } from '@/types';

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
  onSubmit: (req: ModifyRouteRequest) => Promise<void>;
  onEachSubmitted?: (route: Route) => void;
  onComplete?: () => void;
}

export function BatchModifyDialog({
  routes, open, onOpenChange, onSubmit, onEachSubmitted, onComplete,
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

  const [submitting, setSubmitting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [errors, setErrors] = useState<{ route: Route; message: string }[]>([]);

  // Load enums once per mount
  useEffect(() => {
    apiService.getRouteEnums().then(res => {
      if (res.success && res.data) {
        setOrderTypes(res.data.orderTypes);
        setTifOptions(res.data.tifOptions);
      }
    }).catch(() => { /* ignore — submission still works with raw string values */ });
  }, []);

  // Reset fields on open
  useEffect(() => {
    if (open) {
      setNewQty(''); setNewOrderType(''); setNewLimitPrice('');
      setNewStopPrice(''); setNewTif(''); setNewNotes(''); setNotesDirty(false);
      setProgress(0); setErrors([]);
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
    (notesDirty ? 1 : 0);

  const run = async () => {
    if (dirtyFieldCount === 0) return;
    setSubmitting(true); setProgress(0); setErrors([]);
    const failures: { route: Route; message: string }[] = [];

    // Validate once up-front to fail fast
    let qtyParsed: number | undefined;
    if (newQty !== '') {
      qtyParsed = parseInt(newQty, 10);
      if (!Number.isFinite(qtyParsed) || qtyParsed <= 0) {
        setErrors([{ route: routes[0], message: 'Quantity must be a positive integer' }]);
        setSubmitting(false); return;
      }
    }

    for (let i = 0; i < routes.length; i++) {
      const r = routes[i];
      const req: ModifyRouteRequest = { sequence: r.sequence, routeId: r.routeId };
      if (qtyParsed !== undefined) {
        if (qtyParsed < r.filled) {
          failures.push({ route: r, message: `Target qty ${qtyParsed} below filled ${r.filled}` });
          setProgress(i + 1); continue;
        }
        req.amount = qtyParsed;
      }
      if (newOrderType !== '') {
        req.orderType = newOrderType;
        req.tif = newTif !== '' ? newTif : (r.tif || 'DAY');
        const needsLimit = currentOrderType?.needsLimit ?? false;
        const needsStop = currentOrderType?.needsStop ?? false;
        req.limitPrice = needsLimit ? (newLimitPrice !== '' ? parseFloat(newLimitPrice) : r.limitPrice ?? null) : null;
        req.stopPrice = needsStop ? (newStopPrice !== '' ? parseFloat(newStopPrice) : r.stopPrice ?? null) : null;
      } else {
        // Order-type not being changed: only touch price / tif if user typed something
        if (newLimitPrice !== '') req.limitPrice = parseFloat(newLimitPrice);
        if (newStopPrice !== '') req.stopPrice = parseFloat(newStopPrice);
        if (newTif !== '') req.tif = newTif;
      }
      if (notesDirty) req.notes = newNotes;

      try {
        await onSubmit(req);
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
      <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Batch Modify — {routes.length} route{routes.length === 1 ? '' : 's'}</DialogTitle>
          <DialogDescription>
            Only common editable fields are shown. Leave a field empty to keep each route's current
            value. Broker / Strategy editing is per-route only (submit individually from the row menu).
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
                placeholder="unchanged" className="h-8 font-mono" />
            </div>
            <div>
              <Label className="text-xs">New Order Type</Label>
              <Select value={newOrderType || '__none__'} onValueChange={(v) => setNewOrderType(v === '__none__' ? '' : v)}>
                <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">(unchanged)</SelectItem>
                  {orderTypes.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">New TIF</Label>
              <Select value={newTif || '__none__'} onValueChange={(v) => setNewTif(v === '__none__' ? '' : v)}>
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
                placeholder="unchanged" className="h-8 font-mono" />
            </div>
            <div>
              <Label className="text-xs">New Stop Price</Label>
              <Input type="number" step="0.01" value={newStopPrice}
                onChange={(e) => setNewStopPrice(e.target.value)}
                placeholder="unchanged" className="h-8 font-mono" />
            </div>
            <div>
              <Label className="text-xs">New Notes {notesDirty && <span className="text-amber-600">●</span>}</Label>
              <Input value={newNotes}
                onChange={(e) => { setNewNotes(e.target.value); setNotesDirty(true); }}
                placeholder="(leave blank + don't type to skip)" className="h-8" />
            </div>
          </div>

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
                {routes.map(r => (
                  <tr key={r.id} className="border-t border-border/50">
                    <td className="px-2 py-0.5 font-mono">{r.sequence}.{r.routeId}</td>
                    <td className="px-2 py-0.5">{r.ticker || '-'}</td>
                    <td className="px-2 py-0.5 font-mono">{r.broker}</td>
                    <td className="px-2 py-0.5 text-right font-mono-numbers">{r.amount} → {r.filled}</td>
                    <td className="px-2 py-0.5">{r.orderType || '-'} / {r.tif || '-'}</td>
                    <td className="px-2 py-0.5">{r.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {submitting && <p className="text-xs text-muted-foreground">Submitting {progress} / {routes.length}…</p>}

          {errors.length > 0 && (
            <div className="text-xs text-destructive space-y-1">
              <p className="flex items-center gap-1"><AlertTriangle className="h-3 w-3" />{errors.length} request(s) failed:</p>
              {errors.slice(0, 5).map((e, i) => (
                <p key={i} className="font-mono">  {e.route.sequence}.{e.route.routeId}: {e.message}</p>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>Cancel</Button>
          <Button onClick={run} disabled={submitting || dirtyFieldCount === 0 || routes.length === 0}>
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Apply to {routes.length} route{routes.length === 1 ? '' : 's'} ({dirtyFieldCount} field{dirtyFieldCount === 1 ? '' : 's'})
          </Button>
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
