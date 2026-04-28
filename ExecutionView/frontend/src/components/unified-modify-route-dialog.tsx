/**
 * UnifiedModifyRouteDialog — Bloomberg-style inline Modify Route panel.
 *
 * Design principles (matches Bloomberg terminal Modify Route ticket):
 *   - All editable fields are visible at once, pre-filled with current route values.
 *   - Dirty detection is automatic: any field whose value differs from the opening
 *     snapshot is treated as modified and highlighted in amber.
 *   - No per-section enable checkboxes — the original route state is the baseline,
 *     changes are what the user types. This mirrors Bloomberg's direct-manipulation UX.
 *   - A single ModifyRouteEx request is submitted carrying only dirty fields, which
 *     minimises Bloomberg Cancel/Replace transitions.
 *   - A compact inline "Changes" summary is always visible once anything is dirty,
 *     eliminating the need for a separate review screen.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Loader2, RefreshCw, AlertCircle } from 'lucide-react';
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
import type { Route, ModifyRouteRequest } from '@/types';
import { cachedApiService, apiService } from '@/services/api';
import { BrokerStrategyFields, useStrategyFields } from '@/components/broker-strategy-fields';

/**
 * Order-type / TIF option metadata. The values come from the backend
 * `/api/routes/reference-enums` endpoint so the UI never hard-codes EMSX
 * wire values. See `routes.py::get_route_enums`.
 */
interface OrderTypeOption { value: string; label: string; needsLimit: boolean; needsStop: boolean }
interface TifOption { value: string; label: string }

// Minimal safety fallback used only if the reference endpoint is unreachable.
// The canonical list is served by the backend.
const FALLBACK_ORDER_TYPES: OrderTypeOption[] = [
  { value: 'MKT', label: 'MKT', needsLimit: false, needsStop: false },
  { value: 'LMT', label: 'LMT', needsLimit: true,  needsStop: false },
  { value: 'STP', label: 'STP', needsLimit: false, needsStop: true  },
  { value: 'STOP_LIMIT', label: 'STOP_LIMIT', needsLimit: true, needsStop: true },
];
const FALLBACK_TIF: TifOption[] = [
  { value: 'DAY', label: 'DAY' },
  { value: 'GTC', label: 'GTC' },
  { value: 'IOC', label: 'IOC' },
  { value: 'FOK', label: 'FOK' },
  { value: 'GTD', label: 'GTD' },
];

interface UnifiedModifyRouteDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (request: ModifyRouteRequest) => Promise<void>;
}

interface DiffEntry {
  label: string;
  from: string;
  to: string;
}

const displayValue = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
};

/** Returns the amber highlight class when dirty, otherwise empty. */
const dirtyClass = (dirty: boolean): string =>
  dirty ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-500/60 text-amber-900 dark:text-amber-100' : '';

export function UnifiedModifyRouteDialog({
  route,
  open,
  onOpenChange,
  onSubmit,
}: UnifiedModifyRouteDialogProps) {
  // ----- Original baseline captured when opened -----
  const [origAmount, setOrigAmount] = useState('');
  const [origOrderType, setOrigOrderType] = useState('');
  const [origLimitPrice, setOrigLimitPrice] = useState('');
  const [origStopPrice, setOrigStopPrice] = useState('');
  const [origTif, setOrigTif] = useState('DAY');
  const [origBroker, setOrigBroker] = useState('');
  const [origStrategy, setOrigStrategy] = useState('');
  const [origNotes, setOrigNotes] = useState('');

  // ----- Live editable state -----
  const [amount, setAmount] = useState('');
  const [orderType, setOrderType] = useState('');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [tif, setTif] = useState('DAY');
  const [broker, setBroker] = useState('');
  const [strategy, setStrategy] = useState('');
  const [notes, setNotes] = useState('');

  // Strategy metadata
  const [strategies, setStrategies] = useState<string[]>([]);
  const [isLoadingStrategies, setIsLoadingStrategies] = useState(false);
  const [assetClass, setAssetClass] = useState('EQTY');
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Editable strategy fields — shared between Modify Route and Route Order.
  const strategyFieldsState = useStrategyFields(broker, strategy, assetClass);
  const { fields: strategyFields, setFields: setStrategyFields, isLoading: isLoadingFields,
    refresh: refreshStrategyFields, dirty: dirtyStrategyFields, toStrategyParams } = strategyFieldsState;

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Reference enums fetched from backend (single source of truth)
  const [orderTypes, setOrderTypes] = useState<OrderTypeOption[]>(FALLBACK_ORDER_TYPES);
  const [tifOptions, setTifOptions] = useState<TifOption[]>(FALLBACK_TIF);

  // Fetch reference enums once per mount (they are static for a session).
  useEffect(() => {
    let cancelled = false;
    apiService.getRouteEnums().then(res => {
      if (cancelled || !res.success || !res.data) return;
      if (Array.isArray(res.data.orderTypes) && res.data.orderTypes.length > 0) setOrderTypes(res.data.orderTypes);
      if (Array.isArray(res.data.tifOptions) && res.data.tifOptions.length > 0) setTifOptions(res.data.tifOptions);
    }).catch(() => { /* fall back to FALLBACK_* */ });
    return () => { cancelled = true; };
  }, []);

  // Derived: which order-type is currently selected and whether it needs limit / stop
  const currentOrderType = orderTypes.find(o => o.value === orderType);

  // Reset on open
  useEffect(() => {
    if (open && route) {
      const a = route.amount.toString();
      const ot = route.orderType || '';
      const lp = route.limitPrice != null ? route.limitPrice.toString() : '';
      const sp = route.stopPrice != null ? route.stopPrice.toString() : '';
      const t = route.tif || 'DAY';
      const b = route.broker || '';
      const s = route.strategyType || '';
      const n = route.notes || '';

      setOrigAmount(a); setAmount(a);
      setOrigOrderType(ot); setOrderType(ot);
      setOrigLimitPrice(lp); setLimitPrice(lp);
      setOrigStopPrice(sp); setStopPrice(sp);
      setOrigTif(t); setTif(t);
      setOrigBroker(b); setBroker(b);
      setOrigStrategy(s); setStrategy(s);
      setOrigNotes(n); setNotes(n);

      setStrategies([]);
      setError('');
    }
  }, [open, route]);

  // Resolve asset class
  useEffect(() => {
    let cancelled = false;
    if (!open || !route?.ticker) { setAssetClass('EQTY'); return; }
    cachedApiService.resolveAssetClass(route.ticker, 'EQTY')
      .then(ac => { if (!cancelled) setAssetClass(ac || 'EQTY'); })
      .catch(() => { if (!cancelled) setAssetClass('EQTY'); });
    return () => { cancelled = true; };
  }, [open, route?.ticker]);

  const fetchStrategies = useCallback(async (brokerCode: string, force = false) => {
    if (!brokerCode) { setStrategies([]); return; }
    setIsLoadingStrategies(true);
    try {
      const res = await cachedApiService.getBrokerStrategies(brokerCode, assetClass, force);
      setStrategies(res.success && res.data ? res.data.strategies : []);
    } finally {
      setIsLoadingStrategies(false);
    }
  }, [assetClass]);

  const fetchStrategyInfo = useCallback(async (brokerCode: string, strategyName: string, force = false) => {
    if (!brokerCode || !strategyName) { setStrategyFields([]); return; }
    setIsLoadingFields(true);
    try {
      const res = await cachedApiService.getBrokerStrategyInfo(brokerCode, strategyName, assetClass, force);
      if (res.success && res.data) {
        setStrategyFields(res.data.fields.map((f: BrokerStrategyField) => {
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
        setStrategyFields([]);
      }
    } finally {
      setIsLoadingFields(false);
    }
  }, [assetClass]);

  // Load strategy list whenever broker changes
  useEffect(() => {
    if (!open) return;
    if (broker) void fetchStrategies(broker);
  }, [open, broker, fetchStrategies]);

  // Load strategy fields whenever strategy changes
  useEffect(() => {
    if (!open) return;
    if (broker && strategy) void fetchStrategyInfo(broker, strategy);
    else setStrategyFields([]);
  }, [open, broker, strategy, fetchStrategyInfo]);

  const handleRefreshStrategy = async () => {
    if (!broker) return;
    setIsRefreshing(true);
    try {
      await fetchStrategies(broker, true);
      if (strategy) await fetchStrategyInfo(broker, strategy, true);
    } finally { setIsRefreshing(false); }
  };

  // ---- Dirty detection ----
  const dirtyAmount = amount !== origAmount;
  const dirtyOrderType = orderType !== origOrderType;
  const dirtyLimitPrice = limitPrice !== origLimitPrice;
  const dirtyStopPrice = stopPrice !== origStopPrice;
  const dirtyTif = tif !== origTif;
  const dirtyBroker = broker.toUpperCase() !== origBroker.toUpperCase();
  const dirtyStrategy = strategy !== origStrategy;
  const dirtyNotes = notes !== origNotes;
  const dirtyTypeGroup = dirtyOrderType || dirtyLimitPrice || dirtyStopPrice || dirtyTif;
  const dirtyBrokerStrategyGroup = dirtyBroker || dirtyStrategy || dirtyStrategyFields;
  const anyDirty = dirtyAmount || dirtyTypeGroup || dirtyBrokerStrategyGroup || dirtyNotes;

  const showLimitPrice = currentOrderType?.needsLimit ?? false;
  const showStopPrice = currentOrderType?.needsStop ?? false;

  const buildRequest = useCallback((): ModifyRouteRequest => {
    if (!route) throw new Error('No route selected');
    const req: ModifyRouteRequest = {
      sequence: route.sequence,
      routeId: route.routeId,
    };

    if (dirtyAmount) {
      const parsed = parseInt(amount, 10);
      if (!Number.isFinite(parsed) || parsed <= 0) throw new Error('Quantity must be a positive integer');
      if (parsed < route.filled) throw new Error(`Quantity cannot be below filled (${route.filled})`);
      req.amount = parsed;
    }

    if (dirtyTypeGroup) {
      if (!orderType) throw new Error('Order Type is required');
      req.orderType = orderType;
      req.tif = tif || 'DAY';
      const needsLimit = currentOrderType?.needsLimit ?? false;
      const needsStop = currentOrderType?.needsStop ?? false;
      if (needsLimit) {
        if (!limitPrice) throw new Error('Limit Price is required for LMT / STOP_LIMIT');
        req.limitPrice = parseFloat(limitPrice);
      } else {
        req.limitPrice = null;
      }
      if (needsStop) {
        if (!stopPrice) throw new Error('Stop Price is required for STP / STOP_LIMIT');
        req.stopPrice = parseFloat(stopPrice);
      } else {
        req.stopPrice = null;
      }
    }

    if (dirtyBrokerStrategyGroup) {
      if (!strategy) throw new Error('Please select a strategy');
      if (dirtyBroker) {
        if (!broker.trim()) throw new Error('Please enter a broker code');
        req.broker = broker.trim().toUpperCase();
      }
      req.strategyParams = toStrategyParams(strategy) ?? {
        strategyName: strategy,
        fields: [],
      };
    }

    if (dirtyNotes) req.notes = notes;

    return req;
  }, [route, dirtyAmount, dirtyTypeGroup, dirtyBrokerStrategyGroup, dirtyBroker, dirtyNotes,
      amount, orderType, tif, limitPrice, stopPrice, broker, strategy, toStrategyParams, notes,
      currentOrderType]);

  const diff = useMemo<DiffEntry[]>(() => {
    if (!route || !anyDirty) return [];
    const entries: DiffEntry[] = [];
    if (dirtyAmount) entries.push({ label: 'Qty', from: displayValue(origAmount), to: displayValue(amount) });
    if (dirtyOrderType) entries.push({ label: 'Type', from: displayValue(origOrderType), to: displayValue(orderType) });
    if (dirtyLimitPrice) entries.push({ label: 'Limit Price', from: displayValue(origLimitPrice), to: displayValue(limitPrice) });
    if (dirtyStopPrice) entries.push({ label: 'Stop Price', from: displayValue(origStopPrice), to: displayValue(stopPrice) });
    if (dirtyTif) entries.push({ label: 'TIF', from: displayValue(origTif), to: displayValue(tif) });
    if (dirtyBroker) entries.push({ label: 'Broker', from: displayValue(origBroker), to: displayValue(broker.toUpperCase()) });
    if (dirtyStrategy) entries.push({ label: 'Strategy', from: displayValue(origStrategy), to: displayValue(strategy) });
    strategyFields.forEach(f => {
      if (f.value !== f.originalValue) {
        entries.push({ label: `  └ ${f.fieldName}`, from: displayValue(f.originalValue), to: displayValue(f.value) });
      } else if (f.disabled !== f.originalDisabled) {
        entries.push({ label: `  └ ${f.fieldName}`, from: f.originalDisabled ? '(off)' : '(on)', to: f.disabled ? '(off)' : '(on)' });
      }
    });
    if (dirtyNotes) entries.push({ label: 'Notes', from: displayValue(origNotes), to: displayValue(notes) });
    return entries;
  }, [route, anyDirty, dirtyAmount, dirtyOrderType, dirtyLimitPrice, dirtyStopPrice, dirtyTif,
      dirtyBroker, dirtyStrategy, dirtyNotes,
      origAmount, amount, origOrderType, orderType, origLimitPrice, limitPrice,
      origStopPrice, stopPrice, origTif, tif, origBroker, broker, origStrategy, strategy,
      strategyFields, origNotes, notes]);

  const handleSubmit = async () => {
    setError('');
    if (!anyDirty) { setError('No changes to submit'); return; }
    setIsSubmitting(true);
    try {
      const req = buildRequest();
      await onSubmit(req);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Modify Route</DialogTitle>
          <DialogDescription>
            Edit fields directly. Changed cells are highlighted in amber and will be submitted in a single
            <code className="mx-1 px-1 bg-muted rounded text-xs">ModifyRouteEx</code> call.
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-3 py-2">
            {/* Route snapshot header */}
            <div className="grid grid-cols-5 gap-3 text-xs bg-secondary/50 p-3 rounded">
              <div><div className="text-muted-foreground">Route</div><div className="font-mono font-semibold">{route.sequence}.{route.routeId}</div></div>
              <div><div className="text-muted-foreground">Ticker</div><div className="font-semibold">{route.ticker || '-'}</div></div>
              <div><div className="text-muted-foreground">Side</div><div className="font-semibold">{route.side}</div></div>
              <div><div className="text-muted-foreground">Filled / Qty</div><div className="font-mono-numbers">{route.filled} / {route.amount}</div></div>
              <div><div className="text-muted-foreground">Status / Avg</div><div>{route.status} / {route.avgPrice ?? '-'}</div></div>
            </div>

            {/* Row 1: Side / Qty / Ticker / Type / Limit / TIF (Bloomberg ticket layout) */}
            <div className="grid grid-cols-6 gap-2">
              <FieldBlock label="Side" required>
                <Input value={route.side} disabled className="h-8 font-mono" />
              </FieldBlock>
              <FieldBlock label="R Qty" required dirty={dirtyAmount}>
                <Input
                  type="number"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  min={route.filled}
                  className={`h-8 font-mono ${dirtyClass(dirtyAmount)}`}
                />
              </FieldBlock>
              <FieldBlock label="Ticker" required>
                <Input value={route.ticker || ''} disabled className="h-8 font-mono" />
              </FieldBlock>
              <FieldBlock label="Type" required dirty={dirtyOrderType}>
                <Select value={orderType} onValueChange={setOrderType}>
                  <SelectTrigger className={`h-8 ${dirtyClass(dirtyOrderType)}`}><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {orderTypes.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </FieldBlock>
              <FieldBlock label="Limit Price" dirty={dirtyLimitPrice}>
                <Input
                  type="number"
                  step="0.01"
                  value={limitPrice}
                  onChange={(e) => setLimitPrice(e.target.value)}
                  disabled={!showLimitPrice}
                  placeholder={showLimitPrice ? '' : 'n/a'}
                  className={`h-8 font-mono ${dirtyClass(dirtyLimitPrice)}`}
                />
              </FieldBlock>
              <FieldBlock label="TIF" required dirty={dirtyTif}>
                <Select value={tif} onValueChange={setTif}>
                  <SelectTrigger className={`h-8 ${dirtyClass(dirtyTif)}`}><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {tifOptions.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </FieldBlock>
            </div>

            {/* Row 2: Broker (R Dest) / Strategy / Stop Price */}
            <div className="grid grid-cols-6 gap-2">
              <FieldBlock
                label="R Dest (Broker)"
                required
                dirty={false}
                hint="Read-only — EMSX ModifyRouteEx does not support changing broker. To switch broker: Cancel this route, then Route to the new broker."
              >
                <Input
                  value={broker}
                  readOnly
                  disabled
                  className="h-8 font-mono opacity-70 cursor-not-allowed"
                />
              </FieldBlock>
              <FieldBlock label="Strategy" dirty={dirtyStrategy} className="col-span-2">
                {isLoadingStrategies ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground h-8 px-2">
                    <Loader2 className="h-3 w-3 animate-spin" /> Loading…
                  </div>
                ) : (
                  <div className="flex items-center gap-1">
                    <Select value={strategy || '__none__'} onValueChange={(v) => setStrategy(v === '__none__' ? '' : v)} disabled={strategies.length === 0}>
                      <SelectTrigger className={`h-8 flex-1 ${dirtyClass(dirtyStrategy)}`}><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {strategies.map(s => <SelectItem key={s || '__none__'} value={s || '__none__'}>{s || '(None / DMA)'}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    <button type="button" onClick={handleRefreshStrategy} disabled={isRefreshing || !broker}
                      className="p-1 rounded hover:bg-secondary disabled:opacity-40" title="Refresh broker / strategy list">
                      <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                )}
              </FieldBlock>
              <FieldBlock label="Stop Price" dirty={dirtyStopPrice}>
                <Input
                  type="number"
                  step="0.01"
                  value={stopPrice}
                  onChange={(e) => setStopPrice(e.target.value)}
                  disabled={!showStopPrice}
                  placeholder={showStopPrice ? '' : 'n/a'}
                  className={`h-8 font-mono ${dirtyClass(dirtyStopPrice)}`}
                />
              </FieldBlock>
              <FieldBlock label="Notes" dirty={dirtyNotes} className="col-span-2">
                <Input value={notes} onChange={(e) => setNotes(e.target.value)}
                  className={`h-8 ${dirtyClass(dirtyNotes)}`} />
              </FieldBlock>
            </div>

            {/* Strategy parameters (shared with Route Order) */}
            {strategy && (
              <BrokerStrategyFields
                fields={strategyFields}
                setFields={setStrategyFields}
                isLoading={isLoadingFields}
              />
            )}

            {/* Inline diff summary — always visible when anything is dirty */}
            {anyDirty && (
              <div className="border border-amber-500/40 bg-amber-50/60 dark:bg-amber-950/20 rounded p-2">
                <div className="flex items-center gap-2 text-xs font-medium mb-1 text-amber-900 dark:text-amber-100">
                  <AlertCircle className="h-3.5 w-3.5" />
                  Changes ({diff.length})
                </div>
                <table className="w-full text-[11px]">
                  <tbody>
                    {diff.map((e, i) => (
                      <tr key={i}>
                        <td className="pr-3 py-0.5 font-medium whitespace-nowrap">{e.label}</td>
                        <td className="pr-2 py-0.5 font-mono text-muted-foreground line-through">{e.from}</td>
                        <td className="pr-2 py-0.5 font-mono text-primary">→ {e.to}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting || !anyDirty}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Submit ({diff.length} change{diff.length === 1 ? '' : 's'})
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface FieldBlockProps {
  label: string;
  required?: boolean;
  dirty?: boolean;
  className?: string;
  hint?: string;
  children: React.ReactNode;
}

function FieldBlock({ label, required, dirty, className, hint, children }: FieldBlockProps) {
  return (
    <div className={`space-y-1 ${className || ''}`} title={hint}>
      <Label className={`text-[11px] ${dirty ? 'text-amber-700 dark:text-amber-300 font-semibold' : 'text-muted-foreground'}`}>
        {label}{required && <span className="text-destructive">*</span>}
      </Label>
      {children}
      {hint && <p className="text-[10px] text-muted-foreground italic leading-tight">{hint}</p>}
    </div>
  );
}
