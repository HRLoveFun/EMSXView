import { useState, useEffect, useCallback } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { Route, BrokerStrategyField } from '@execution/types';
import { cachedApiService } from '@execution/services/execution-api';

type BrokerStrategyMode = 'strategy' | 'broker';

interface StrategyFieldState {
  fieldName: string;
  value: string;
  disabled: boolean;
  defaultValue: string;
}

interface BrokerStrategyDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirmStrategy: (route: Route, strategyName: string, fields: { value: string; disabled: boolean }[]) => Promise<void>;
  onConfirmBroker: (route: Route, broker: string, strategyName: string, fields: { value: string; disabled: boolean }[]) => Promise<void>;
  availableBrokers?: string[];
}

export function BrokerStrategyDialog({
  route, open, onOpenChange, onConfirmStrategy, onConfirmBroker, availableBrokers = [],
}: BrokerStrategyDialogProps) {
  const [mode, setMode] = useState<BrokerStrategyMode>('strategy');
  const [newBroker, setNewBroker] = useState('');
  const [strategies, setStrategies] = useState<string[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState('');
  const [strategyFields, setStrategyFields] = useState<StrategyFieldState[]>([]);
  const [isLoadingStrategies, setIsLoadingStrategies] = useState(false);
  const [isLoadingFields, setIsLoadingFields] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [cacheStatus, setCacheStatus] = useState<string>('');
  const [assetClass, setAssetClass] = useState('EQTY');
  const [preloadingProgress, setPreloadingProgress] = useState<{ current: number; total: number } | null>(null);
  const [preloadedStrategies, setPreloadedStrategies] = useState<Set<string>>(new Set());
  const [brokerFetchTimer, setBrokerFetchTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const effectiveBroker = mode === 'strategy' ? (route?.broker || '') : newBroker.trim();

  const preloadAllStrategyParams = useCallback(async (broker: string, strategyList: string[]) => {
    if (!broker || strategyList.length === 0) return;
    const uncachedStrategies = strategyList.filter(strategy => {
      const cacheKey = `emsx_cache_strategy_info_${broker}_${strategy}`;
      return !localStorage.getItem(cacheKey);
    });
    if (uncachedStrategies.length === 0) {
      setPreloadedStrategies(new Set(strategyList));
      return;
    }
    setPreloadingProgress({ current: 0, total: uncachedStrategies.length });
    const loaded = new Set<string>();
    let completed = 0;
    const batchSize = 3;
    for (let i = 0; i < uncachedStrategies.length; i += batchSize) {
      const batch = uncachedStrategies.slice(i, i + batchSize);
      await Promise.all(batch.map(async (strategy) => {
        try { await cachedApiService.getBrokerStrategyInfo(broker, strategy, assetClass, false); loaded.add(strategy); } catch { /* preload best-effort */ }
        completed++;
        setPreloadingProgress({ current: completed, total: uncachedStrategies.length });
      }));
      if (i + batchSize < uncachedStrategies.length) await new Promise(resolve => setTimeout(resolve, 500));
    }
    setPreloadedStrategies(prev => new Set([...prev, ...loaded]));
    setPreloadingProgress(null);
  }, [assetClass]);

  const fetchStrategies = useCallback(async (broker: string, forceRefresh = false) => {
    if (!broker) { setStrategies([]); return; }
    setIsLoadingStrategies(true); setError('');
    try {
      const res = await cachedApiService.getBrokerStrategies(broker, assetClass, forceRefresh);
      if (res.success && res.data) {
        setStrategies(res.data.strategies);
        preloadAllStrategyParams(broker, res.data.strategies);
      } else {
        setError(res.error || 'Failed to load strategies'); setStrategies([]);
      }
    } catch {
      setError('Failed to load strategies'); setStrategies([]);
    } finally { setIsLoadingStrategies(false); }
  }, [assetClass, preloadAllStrategyParams]);

  const fetchStrategyInfo = useCallback(async (broker: string, strategy: string, forceRefresh = false) => {
    if (!broker || !strategy) { setStrategyFields([]); return; }
    setIsLoadingFields(true); setError('');
    try {
      const res = await cachedApiService.getBrokerStrategyInfo(broker, strategy, assetClass, forceRefresh);
      if (res.success && res.data) {
        setStrategyFields(res.data.fields.map((f: BrokerStrategyField) => ({
          fieldName: f.fieldName, value: f.stringValue || '',
          disabled: f.disable === '1', defaultValue: f.stringValue || '',
        })));
      } else {
        setError(res.error || 'Failed to load strategy parameters'); setStrategyFields([]);
      }
    } catch { setError('Failed to load strategy parameters'); setStrategyFields([]); }
    finally { setIsLoadingFields(false); }
  }, [assetClass]);

  useEffect(() => { let cancelled = false;
    if (!open || !route?.ticker) { setAssetClass('EQTY'); return; }
    cachedApiService.resolveAssetClass(route.ticker, 'EQTY').then(a => { if (!cancelled) setAssetClass(a || 'EQTY'); }).catch(() => { if (!cancelled) setAssetClass('EQTY'); });
    return () => { cancelled = true; };
  }, [open, route?.ticker]);

  useEffect(() => {
    if (open && route) {
      setMode('strategy'); setNewBroker(''); setSelectedStrategy(route.strategyType || '');
      setStrategyFields([]); setError(''); setCacheStatus(''); setPreloadingProgress(null); setPreloadedStrategies(new Set());
      if (route.broker) fetchStrategies(route.broker);
    }
  }, [open, route, fetchStrategies]);

  const handleRefresh = useCallback(async () => {
    if (!effectiveBroker) return; setIsRefreshing(true); setCacheStatus('Refreshing...');
    try { await fetchStrategies(effectiveBroker, true); if (selectedStrategy) await fetchStrategyInfo(effectiveBroker, selectedStrategy, true); setCacheStatus('Updated'); }
    catch { setCacheStatus('Refresh failed'); }
    finally { setIsRefreshing(false); }
  }, [effectiveBroker, selectedStrategy, fetchStrategies, fetchStrategyInfo]);

  const handleModeChange = useCallback((newMode: BrokerStrategyMode) => {
    setMode(newMode); setSelectedStrategy(''); setStrategyFields([]); setError('');
    if (newMode === 'strategy' && route?.broker) fetchStrategies(route.broker); else setStrategies([]);
  }, [route, fetchStrategies]);

  const handleBrokerChange = useCallback((value: string) => {
    setNewBroker(value); setSelectedStrategy(''); setStrategyFields([]); setStrategies([]); setError('');
    if (brokerFetchTimer) clearTimeout(brokerFetchTimer);
    const trimmed = value.trim();
    if (trimmed.length >= 2) { const timer = setTimeout(() => fetchStrategies(trimmed), 400); setBrokerFetchTimer(timer); }
  }, [brokerFetchTimer, fetchStrategies]);

  useEffect(() => {
    if (open && effectiveBroker && selectedStrategy) {
      const cacheKey = `emsx_cache_strategy_info_${effectiveBroker}_${selectedStrategy}`;
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (parsed.data?.fields) {
            setStrategyFields(parsed.data.fields.map((f: BrokerStrategyField) => ({
              fieldName: f.fieldName, value: f.stringValue || '',
              disabled: f.disable === '1', defaultValue: f.stringValue || '',
            })));
            return;
          }
        } catch { /* fall through to API */ }
      }
      fetchStrategyInfo(effectiveBroker, selectedStrategy);
    } else { setStrategyFields([]); }
  }, [open, effectiveBroker, selectedStrategy, fetchStrategyInfo]);

  const handleConfirm = async () => {
    if (!route || !selectedStrategy) return;
    setIsSubmitting(true);
    const fields = strategyFields.map(f => ({ value: f.value, disabled: f.disabled }));
    try {
      if (mode === 'broker') {
        if (!newBroker.trim()) { setError('Please enter a broker code'); setIsSubmitting(false); return; }
        await onConfirmBroker(route, newBroker.trim(), selectedStrategy, fields);
      } else { await onConfirmStrategy(route, selectedStrategy, fields); }
      onOpenChange(false);
    } finally { setIsSubmitting(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle>Broker & Strategy</DialogTitle>
            <button onClick={handleRefresh} disabled={isRefreshing || !effectiveBroker}
              className="p-1.5 rounded-md hover:bg-secondary disabled:opacity-40" title="Refresh from API">
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <DialogDescription>
            Change the execution strategy, or switch to a different broker.
            {cacheStatus && <span className="ml-2 text-xs text-muted-foreground">({cacheStatus})</span>}
          </DialogDescription>
        </DialogHeader>
        {route && (
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-3 gap-3 text-sm bg-secondary/50 p-3 rounded">
              <div><span className="text-muted-foreground">Broker:</span><div className="font-semibold">{route.broker || 'N/A'}</div></div>
              <div><span className="text-muted-foreground">Strategy:</span><div className="font-semibold">{route.strategyType || 'None'}</div></div>
              <div><span className="text-muted-foreground">Exch Dest:</span><div className="font-semibold">{route.exchangeDestination || 'N/A'}</div></div>
            </div>
            <div className="flex gap-2">
              <Button variant={mode === 'strategy' ? 'default' : 'outline'} size="sm" className="flex-1" onClick={() => handleModeChange('strategy')}>Change Strategy</Button>
              <Button variant={mode === 'broker' ? 'default' : 'outline'} size="sm" className="flex-1" onClick={() => handleModeChange('broker')}>Change Broker</Button>
            </div>
            {mode === 'broker' && (
              <div className="space-y-2">
                <Label>New Broker</Label>
                {availableBrokers.length > 0 ? (
                  <Select value={newBroker} onValueChange={(v) => handleBrokerChange(v.toUpperCase())}>
                    <SelectTrigger><SelectValue placeholder="Select a broker" /></SelectTrigger>
                    <SelectContent>{availableBrokers.map(b => <SelectItem key={b} value={b}>{b}</SelectItem>)}</SelectContent>
                  </Select>
                ) : (
                  <Input value={newBroker} onChange={e => handleBrokerChange(e.target.value.toUpperCase())}
                    placeholder="Enter broker code (e.g. BMTB)" className="font-mono" />
                )}
              </div>
            )}
            <div className="space-y-2">
              <Label>Strategy</Label>
              {isLoadingStrategies && mode === 'strategy' ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2"><Loader2 className="h-4 w-4 animate-spin" />Loading...</div>
              ) : strategies.length > 0 ? (
                <Select value={selectedStrategy} onValueChange={setSelectedStrategy}>
                  <SelectTrigger><SelectValue placeholder="Select strategy" /></SelectTrigger>
                  <SelectContent>
                    {strategies.map(s => {
                      const isCached = preloadedStrategies.has(s) || localStorage.getItem(`emsx_cache_strategy_info_${effectiveBroker}_${s}`);
                      return <SelectItem key={s} value={s || '__none__'}>{s || '(None / DMA)'}{isCached && <span className="text-xs text-green-500 ml-1">✓</span>}</SelectItem>;
                    })}
                  </SelectContent>
                </Select>
              ) : !isLoadingStrategies ? (<p className="text-sm text-muted-foreground py-2">{mode === 'broker' && !newBroker.trim() ? 'Enter a broker code to load strategies' : error || 'No strategies available'}</p>) : null}
              {preloadingProgress && (
                <div className="space-y-1"><div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3 w-3 animate-spin" />Preloading... ({preloadingProgress.current}/{preloadingProgress.total})</div>
                  <div className="h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full bg-primary transition-all" style={{ width: `${(preloadingProgress.current / preloadingProgress.total) * 100}%` }} /></div>
                </div>
              )}
            </div>
            {selectedStrategy && (
              <div className="space-y-3">
                <Label className="text-sm font-medium">Parameters</Label>
                {isLoadingFields ? (<div className="flex items-center gap-2 text-sm text-muted-foreground py-2"><Loader2 className="h-4 w-4 animate-spin" />Loading...</div>)
                  : strategyFields.length > 0 ? (
                    <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                      {strategyFields.map((field, idx) => (
                        <div key={field.fieldName} className="flex items-center gap-2">
                          <label className="w-32 text-xs text-muted-foreground truncate shrink-0" title={field.fieldName}>{field.fieldName}</label>
                          <Input value={field.disabled ? '' : field.value}
                            onChange={e => setStrategyFields(prev => { const n = [...prev]; n[idx] = { ...n[idx], value: e.target.value, disabled: false }; return n; })}
                            disabled={field.disabled} placeholder={field.disabled ? '(ignored)' : field.defaultValue || ''} className="h-7 text-xs flex-1" />
                          <button type="button" onClick={() => setStrategyFields(prev => { const n = [...prev]; n[idx] = { ...n[idx], disabled: !n[idx].disabled }; return n; })}
                            className={`text-xs px-2 py-1 rounded border shrink-0 ${field.disabled ? 'bg-muted text-muted-foreground border-border' : 'bg-primary/10 text-primary border-primary/30'}`}>
                            {field.disabled ? 'Off' : 'On'}
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (<p className="text-sm text-muted-foreground">No parameters for this strategy</p>)}
              </div>
            )}
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>Cancel</Button>
          <Button onClick={handleConfirm} disabled={isSubmitting || !selectedStrategy}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {mode === 'broker' ? 'Change Broker & Strategy' : 'Change Strategy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
