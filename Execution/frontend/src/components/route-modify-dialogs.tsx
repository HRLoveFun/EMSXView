import { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';
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
import { Badge } from '@/components/ui/badge';
import type { Route, BrokerStrategyField } from '@/types';
import { cachedApiService } from '@/services/api';

// ============================================================================
// Cancel Route Dialog
// ============================================================================
interface CancelRouteDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route) => Promise<void>;
}

export function CancelRouteDialog({
  route,
  open,
  onOpenChange,
  onConfirm,
}: CancelRouteDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleConfirm = async () => {
    if (!route) return;
    setIsSubmitting(true);
    try {
      await onConfirm(route);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            Cancel Route
          </DialogTitle>
          <DialogDescription>
            Are you sure you want to cancel this route? This action will send a cancel request to the execution venue.
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-3 py-4">
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Order Sequence:</span>
                <div className="font-mono">{route.sequence}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Route ID:</span>
                <div className="font-mono">{route.routeId}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Ticker:</span>
                <div className="font-semibold">{route.ticker || '-'}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Status:</span>
                <div><Badge variant="outline">{route.status}</Badge></div>
              </div>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// Modify Amount Dialog
// ============================================================================
interface ModifyAmountDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route, newAmount: number) => Promise<void>;
}

export function ModifyAmountDialog({
  route,
  open,
  onOpenChange,
  onConfirm,
}: ModifyAmountDialogProps) {
  const [newAmount, setNewAmount] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (route) {
      setNewAmount(route.amount.toString());
      setError('');
    }
  }, [route, open]);

  const handleConfirm = async () => {
    if (!route) return;
    const amount = parseInt(newAmount, 10);
    if (isNaN(amount) || amount <= 0) {
      setError('Please enter a valid positive number');
      return;
    }
    if (amount < route.filled) {
      setError(`New amount must be greater than or equal to filled quantity (${route.filled})`);
      return;
    }
    setIsSubmitting(true);
    try {
      await onConfirm(route, amount);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modify Quantity</DialogTitle>
          <DialogDescription>
            Change the quantity for this route. New quantity must be at least the filled amount.
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-4 py-4">
            <div className="grid grid-cols-2 gap-4 text-sm bg-secondary/50 p-3 rounded">
              <div>
                <span className="text-muted-foreground">Current Qty:</span>
                <div className="font-mono font-semibold">{route.amount}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Filled:</span>
                <div className="font-mono">{route.filled}</div>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="new-amount">New Quantity</Label>
              <Input
                id="new-amount"
                type="number"
                value={newAmount}
                onChange={(e) => {
                  setNewAmount(e.target.value);
                  setError('');
                }}
                min={route.filled}
                className={error ? 'border-destructive' : ''}
              />
              {error && <p className="text-xs text-destructive">{error}</p>}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// Modify Order Type Dialog
// ============================================================================
const ORDER_TYPES = [
  { value: 'MKT', label: 'Market (MKT)' },
  { value: 'LMT', label: 'Limit (LMT)' },
  { value: 'STP', label: 'Stop (STP)' },
  { value: 'STOP_LIMIT', label: 'Stop Limit (STOP_LIMIT)' },
];

const TIF_OPTIONS = [
  { value: 'DAY', label: 'Day' },
  { value: 'GTC', label: 'Good Till Cancelled' },
  { value: 'IOC', label: 'Immediate or Cancel' },
  { value: 'FOK', label: 'Fill or Kill' },
  { value: 'GTD', label: 'Good Till Date' },
];

interface ModifyOrderTypeDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route, orderType: string, limitPrice: number | null, stopPrice: number | null, tif: string) => Promise<void>;
}

export function ModifyOrderTypeDialog({
  route,
  open,
  onOpenChange,
  onConfirm,
}: ModifyOrderTypeDialogProps) {
  const [orderType, setOrderType] = useState('');
  const [limitPrice, setLimitPrice] = useState('');
  const [stopPrice, setStopPrice] = useState('');
  const [tif, setTif] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (route) {
      setOrderType(route.orderType);
      setLimitPrice(route.limitPrice?.toString() || '');
      setStopPrice(route.stopPrice?.toString() || '');
      setTif(route.tif || 'DAY');
      setError('');
    }
  }, [route, open]);

  const handleConfirm = async () => {
    if (!route) return;

    // Validation
    if (orderType === 'LMT' && !limitPrice) {
      setError('Limit price is required for Limit orders');
      return;
    }
    if ((orderType === 'STP' || orderType === 'STOP_LIMIT') && !stopPrice) {
      setError('Stop price is required for Stop orders');
      return;
    }

    setIsSubmitting(true);
    try {
      await onConfirm(
        route,
        orderType,
        limitPrice ? parseFloat(limitPrice) : null,
        stopPrice ? parseFloat(stopPrice) : null,
        tif
      );
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const showLimitPrice = orderType === 'LMT' || orderType === 'STOP_LIMIT';
  const showStopPrice = orderType === 'STP' || orderType === 'STOP_LIMIT';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modify Order Type</DialogTitle>
          <DialogDescription>
            Change the order type and related parameters.
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Order Type</Label>
              <Select value={orderType} onValueChange={setOrderType}>
                <SelectTrigger>
                  <SelectValue placeholder="Select order type" />
                </SelectTrigger>
                <SelectContent>
                  {ORDER_TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>
                      {type.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Time In Force</Label>
              <Select value={tif} onValueChange={setTif}>
                <SelectTrigger>
                  <SelectValue placeholder="Select TIF" />
                </SelectTrigger>
                <SelectContent>
                  {TIF_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {showLimitPrice && (
              <div className="space-y-2">
                <Label htmlFor="limit-price">Limit Price</Label>
                <Input
                  id="limit-price"
                  type="number"
                  step="0.01"
                  value={limitPrice}
                  onChange={(e) => {
                    setLimitPrice(e.target.value);
                    setError('');
                  }}
                  placeholder="Enter limit price"
                />
              </div>
            )}

            {showStopPrice && (
              <div className="space-y-2">
                <Label htmlFor="stop-price">Stop Price</Label>
                <Input
                  id="stop-price"
                  type="number"
                  step="0.01"
                  value={stopPrice}
                  onChange={(e) => {
                    setStopPrice(e.target.value);
                    setError('');
                  }}
                  placeholder="Enter stop price"
                />
              </div>
            )}

            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// Modify Limit Price Dialog
// ============================================================================
interface ModifyLimitPriceDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route, limitPrice: number | null) => Promise<void>;
}

export function ModifyLimitPriceDialog({
  route,
  open,
  onOpenChange,
  onConfirm,
}: ModifyLimitPriceDialogProps) {
  const [limitPrice, setLimitPrice] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (route) {
      setLimitPrice(route.limitPrice?.toString() || '');
    }
  }, [route, open]);

  const handleConfirm = async () => {
    if (!route) return;
    setIsSubmitting(true);
    try {
      const price = limitPrice ? parseFloat(limitPrice) : null;
      await onConfirm(route, price);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Modify Limit Price</DialogTitle>
          <DialogDescription>
            Change the limit price for this route.
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-4 py-4">
            <div className="text-sm bg-secondary/50 p-3 rounded">
              <span className="text-muted-foreground">Current Limit Price:</span>
              <div className="font-mono font-semibold">{route.limitPrice || 'Not set'}</div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="new-limit-price">New Limit Price</Label>
              <Input
                id="new-limit-price"
                type="number"
                step="0.01"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                placeholder="Enter new limit price"
              />
              <p className="text-xs text-muted-foreground">
                Leave empty to clear the limit price
              </p>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ============================================================================
// Broker & Strategy Dialog — Unified dialog for broker / strategy changes
// ============================================================================

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
  route,
  open,
  onOpenChange,
  onConfirmStrategy,
  onConfirmBroker,
  availableBrokers = [],
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
  
  // Background preloading state
  const [preloadingProgress, setPreloadingProgress] = useState<{ current: number; total: number } | null>(null);
  const [preloadedStrategies, setPreloadedStrategies] = useState<Set<string>>(new Set());

  // The effective broker: current broker in "strategy" mode, user-entered broker in "broker" mode
  const effectiveBroker = mode === 'strategy' ? (route?.broker || '') : newBroker.trim();

  // Background preload all strategy parameters for a broker - MUST be defined before fetchStrategies
  const preloadAllStrategyParams = useCallback(async (broker: string, strategyList: string[]) => {
    if (!broker || strategyList.length === 0) return;
    
    // Check which strategies are already cached
    const uncachedStrategies = strategyList.filter(strategy => {
      const cacheKey = `emsx_cache_strategy_info_${broker}_${strategy}`;
      const cached = localStorage.getItem(cacheKey);
      return !cached; // Only preload uncached strategies
    });
    
    if (uncachedStrategies.length === 0) {
      console.log(`[BrokerStrategy] All ${strategyList.length} strategies already cached for ${broker}`);
      setPreloadedStrategies(new Set(strategyList));
      return;
    }
    
    console.log(`[BrokerStrategy] Preloading ${uncachedStrategies.length} uncached strategies for ${broker}:`, uncachedStrategies);
    setPreloadingProgress({ current: 0, total: uncachedStrategies.length });
    
    const loaded = new Set<string>();
    let completed = 0;
    
    // Process in batches of 3 to avoid overwhelming the API
    const batchSize = 3;
    for (let i = 0; i < uncachedStrategies.length; i += batchSize) {
      const batch = uncachedStrategies.slice(i, i + batchSize);
      
      // Process batch in parallel
      await Promise.all(
        batch.map(async (strategy) => {
          try {
            console.log(`[BrokerStrategy] Preloading ${broker}/${strategy}...`);
            const res = await cachedApiService.getBrokerStrategyInfo(broker, strategy, 'EQTY', false);
            
            if (res.success) {
              loaded.add(strategy);
              console.log(`[BrokerStrategy] ✓ Preloaded ${broker}/${strategy}`);
            } else {
              console.warn(`[BrokerStrategy] ✗ Failed to preload ${broker}/${strategy}:`, res.error);
            }
          } catch (err) {
            console.error(`[BrokerStrategy] ✗ Error preloading ${broker}/${strategy}:`, err);
          }
          
          completed++;
          setPreloadingProgress({ current: completed, total: uncachedStrategies.length });
        })
      );
      
      // Small delay between batches to be gentle on the API
      if (i + batchSize < uncachedStrategies.length) {
        await new Promise(resolve => setTimeout(resolve, 500));
      }
    }
    
    setPreloadedStrategies(prev => new Set([...prev, ...loaded]));
    setPreloadingProgress(null);
    console.log(`[BrokerStrategy] Preloading complete for ${broker}: ${loaded.size}/${uncachedStrategies.length} loaded`);
  }, []);

  // Fetch available strategies for a broker (with caching)
  const fetchStrategies = useCallback(async (broker: string, forceRefresh = false) => {
    if (!broker) {
      setStrategies([]);
      return;
    }
    setIsLoadingStrategies(true);
    setError('');
    try {
      const res = await cachedApiService.getBrokerStrategies(broker, 'EQTY', forceRefresh);
      console.log('[BrokerStrategy] Fetch strategies response:', { broker, success: res.success, error: res.error, message: res.message, data: res.data });
      if (res.success && res.data) {
        setStrategies(res.data.strategies);
        // Trigger background preloading of all strategy parameters
        preloadAllStrategyParams(broker, res.data.strategies);
      } else {
        setError(res.error || 'Failed to load strategies');
        setStrategies([]);
      }
    } catch (err) {
      console.error('[BrokerStrategy] Fetch strategies error:', err);
      setError('Failed to load strategies');
      setStrategies([]);
    } finally {
      setIsLoadingStrategies(false);
    }
  }, [preloadAllStrategyParams]);

  // Fetch strategy parameters (with caching)
  const fetchStrategyInfo = useCallback(async (broker: string, strategy: string, forceRefresh = false) => {
    if (!broker || !strategy) {
      setStrategyFields([]);
      return;
    }
    setIsLoadingFields(true);
    setError('');
    
    // Log cache status
    const cacheKey = `strategy_info_${broker}_${strategy}`;
    const cached = localStorage.getItem(`emsx_cache_${cacheKey}`);
    console.log(`[BrokerStrategy] Strategy info cache for ${broker}/${strategy}:`, cached ? 'EXISTS' : 'NOT CACHED');
    
    try {
      const res = await cachedApiService.getBrokerStrategyInfo(broker, strategy, 'EQTY', forceRefresh);
      console.log('[BrokerStrategy] Fetch strategy info response:', { broker, strategy, success: res.success, error: res.error, message: res.message, data: res.data });
      if (res.success && res.data) {
        setStrategyFields(
          res.data.fields.map((f: BrokerStrategyField) => ({
            fieldName: f.fieldName,
            value: f.stringValue || '',
            disabled: f.disable === '1',
            defaultValue: f.stringValue || '',
          }))
        );
      } else {
        setError(res.error || 'Failed to load strategy parameters');
        setStrategyFields([]);
      }
    } catch (err) {
      console.error('[BrokerStrategy] Fetch strategy info error:', err);
      setError('Failed to load strategy parameters');
      setStrategyFields([]);
    } finally {
      setIsLoadingFields(false);
    }
  }, []);

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (open && route) {
      setMode('strategy');
      setNewBroker('');
      setSelectedStrategy(route.strategyType || '');
      setStrategyFields([]);
      setError('');
      setCacheStatus('');
      setPreloadingProgress(null);
      setPreloadedStrategies(new Set());
      // Load strategies for the current broker (use cache if available)
      if (route.broker) {
        fetchStrategies(route.broker);
      }
    }
  }, [open, route, fetchStrategies]);

  // Handle manual refresh
  const handleRefresh = useCallback(async () => {
    if (!effectiveBroker) return;
    setIsRefreshing(true);
    setCacheStatus('Refreshing...');
    try {
      await fetchStrategies(effectiveBroker, true);
      if (selectedStrategy) {
        await fetchStrategyInfo(effectiveBroker, selectedStrategy, true);
      }
      setCacheStatus('Updated');
    } catch {
      setCacheStatus('Refresh failed');
    } finally {
      setIsRefreshing(false);
    }
  }, [effectiveBroker, selectedStrategy, fetchStrategies, fetchStrategyInfo]);

  // When mode changes, reload strategies for the effective broker
  const handleModeChange = useCallback((newMode: BrokerStrategyMode) => {
    setMode(newMode);
    setSelectedStrategy('');
    setStrategyFields([]);
    setError('');
    if (newMode === 'strategy' && route?.broker) {
      fetchStrategies(route.broker);
    } else {
      setStrategies([]);
    }
  }, [route, fetchStrategies]);

  // When broker input changes in "broker" mode, fetch strategies after a brief pause
  const [brokerFetchTimer, setBrokerFetchTimer] = useState<ReturnType<typeof setTimeout> | null>(null);
  const handleBrokerChange = useCallback((value: string) => {
    setNewBroker(value);
    setSelectedStrategy('');
    setStrategyFields([]);
    setStrategies([]);
    setError('');
    if (brokerFetchTimer) clearTimeout(brokerFetchTimer);
    const trimmed = value.trim();
    if (trimmed.length >= 2) {
      const timer = setTimeout(() => fetchStrategies(trimmed), 400);
      setBrokerFetchTimer(timer);
    }
  }, [brokerFetchTimer, fetchStrategies]);

  // When strategy selection changes, load its parameters
  useEffect(() => {
    if (open && effectiveBroker && selectedStrategy) {
      // Check if already cached (preloaded)
      const cacheKey = `emsx_cache_strategy_info_${effectiveBroker}_${selectedStrategy}`;
      const cached = localStorage.getItem(cacheKey);
      
      if (cached) {
        console.log(`[BrokerStrategy] Using cached data for ${effectiveBroker}/${selectedStrategy}`);
        try {
          const parsed = JSON.parse(cached);
          if (parsed.data && parsed.data.fields) {
            setStrategyFields(
              parsed.data.fields.map((f: BrokerStrategyField) => ({
                fieldName: f.fieldName,
                value: f.stringValue || '',
                disabled: f.disable === '1',
                defaultValue: f.stringValue || '',
              }))
            );
            return; // Skip API call
          }
        } catch (e) {
          console.warn('[BrokerStrategy] Failed to parse cached data:', e);
        }
      }
      
      // Not cached or invalid cache, fetch from API
      fetchStrategyInfo(effectiveBroker, selectedStrategy);
    } else {
      setStrategyFields([]);
    }
  }, [open, effectiveBroker, selectedStrategy, fetchStrategyInfo]);

  const handleFieldChange = (index: number, value: string) => {
    setStrategyFields(prev => {
      const next = [...prev];
      next[index] = { ...next[index], value, disabled: false };
      return next;
    });
  };

  const handleFieldDisableToggle = (index: number) => {
    setStrategyFields(prev => {
      const next = [...prev];
      next[index] = { ...next[index], disabled: !next[index].disabled };
      return next;
    });
  };

  const handleConfirm = async () => {
    if (!route || !selectedStrategy) return;
    setIsSubmitting(true);
    const fields = strategyFields.map(f => ({ value: f.value, disabled: f.disabled }));
    try {
      if (mode === 'broker') {
        if (!newBroker.trim()) {
          setError('Please enter a broker code');
          setIsSubmitting(false);
          return;
        }
        await onConfirmBroker(route, newBroker.trim(), selectedStrategy, fields);
      } else {
        await onConfirmStrategy(route, selectedStrategy, fields);
      }
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle>Broker & Strategy</DialogTitle>
            <button
              onClick={handleRefresh}
              disabled={isRefreshing || !effectiveBroker}
              className="p-1.5 rounded-md hover:bg-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              title="Refresh from API"
            >
              <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <DialogDescription>
            Change the execution strategy, or switch to a different broker.
            {cacheStatus && (
              <span className="ml-2 text-xs text-muted-foreground">({cacheStatus})</span>
            )}
          </DialogDescription>
        </DialogHeader>

        {route && (
          <div className="space-y-4 py-4">
            {/* Current info */}
            <div className="grid grid-cols-3 gap-3 text-sm bg-secondary/50 p-3 rounded">
              <div>
                <span className="text-muted-foreground">Broker:</span>
                <div className="font-semibold">{route.broker || 'N/A'}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Strategy:</span>
                <div className="font-semibold">{route.strategyType || 'None'}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Exch Dest:</span>
                <div className="font-semibold">{route.exchangeDestination || 'N/A'}</div>
              </div>
            </div>

            {/* Mode selector */}
            <div className="flex gap-2">
              <Button
                variant={mode === 'strategy' ? 'default' : 'outline'}
                size="sm"
                className="flex-1"
                onClick={() => handleModeChange('strategy')}
              >
                Change Strategy
              </Button>
              <Button
                variant={mode === 'broker' ? 'default' : 'outline'}
                size="sm"
                className="flex-1"
                onClick={() => handleModeChange('broker')}
              >
                Change Broker
              </Button>
            </div>

            {/* Broker selection — only in broker mode */}
            {mode === 'broker' && (
              <div className="space-y-2">
                <Label>New Broker</Label>
                {availableBrokers.length > 0 ? (
                  <Select value={newBroker} onValueChange={(value) => handleBrokerChange(value.toUpperCase())}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a broker" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableBrokers.map((broker) => (
                        <SelectItem key={broker} value={broker}>
                          {broker}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    id="new-broker"
                    value={newBroker}
                    onChange={(e) => handleBrokerChange(e.target.value.toUpperCase())}
                    placeholder="Enter broker code (e.g. BMTB)"
                    className="font-mono"
                  />
                )}
                {newBroker.trim().length >= 2 && isLoadingStrategies && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Loading strategies for {newBroker.trim()}...
                  </div>
                )}
              </div>
            )}

            {/* Strategy selector */}
            <div className="space-y-2">
              <Label>Strategy</Label>
              {isLoadingStrategies && mode === 'strategy' ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading strategies for {route.broker}...
                </div>
              ) : strategies.length > 0 ? (
                <Select value={selectedStrategy} onValueChange={setSelectedStrategy}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    {strategies.map((s) => {
                      const isCached = preloadedStrategies.has(s) || localStorage.getItem(`emsx_cache_strategy_info_${effectiveBroker}_${s}`);
                      return (
                        <SelectItem key={s} value={s || '__none__'}>
                          <span className="flex items-center gap-2">
                            {s || '(None / DMA)'}
                            {isCached && <span className="text-xs text-green-500">✓</span>}
                          </span>
                        </SelectItem>
                      );
                    })}
                  </SelectContent>
                </Select>
              ) : !isLoadingStrategies ? (
                <p className="text-sm text-muted-foreground py-2">
                  {mode === 'broker' && !newBroker.trim()
                    ? 'Enter a broker code above to load strategies'
                    : error || 'No strategies available'}
                </p>
              ) : null}
              
              {/* Background preloading progress */}
              {preloadingProgress && (
                <div className="space-y-1">
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Preloading strategy parameters... ({preloadingProgress.current}/{preloadingProgress.total})
                  </div>
                  <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-primary transition-all duration-300"
                      style={{ width: `${(preloadingProgress.current / preloadingProgress.total) * 100}%` }}
                    />
                  </div>
                </div>
              )}
              
              {/* Show cached count when preloading complete */}
              {!preloadingProgress && preloadedStrategies.size > 0 && (
                <div className="text-xs text-muted-foreground">
                  <span className="text-green-500">✓</span> {preloadedStrategies.size} strategy parameters cached
                </div>
              )}
            </div>

            {/* Strategy parameter fields */}
            {selectedStrategy && (
              <div className="space-y-3">
                <Label className="text-sm font-medium">Parameters</Label>
                {isLoadingFields ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading parameters...
                  </div>
                ) : strategyFields.length > 0 ? (
                  <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                    {strategyFields.map((field, idx) => (
                      <div key={field.fieldName} className="flex items-center gap-2">
                        <label className="w-32 text-xs text-muted-foreground truncate shrink-0" title={field.fieldName}>
                          {field.fieldName}
                        </label>
                        <Input
                          value={field.disabled ? '' : field.value}
                          onChange={(e) => handleFieldChange(idx, e.target.value)}
                          disabled={field.disabled}
                          placeholder={field.disabled ? '(ignored)' : field.defaultValue || ''}
                          className="h-7 text-xs flex-1"
                        />
                        <button
                          type="button"
                          onClick={() => handleFieldDisableToggle(idx)}
                          className={`text-xs px-2 py-1 rounded border shrink-0 ${
                            field.disabled
                              ? 'bg-muted text-muted-foreground border-border'
                              : 'bg-primary/10 text-primary border-primary/30'
                          }`}
                          title={field.disabled ? 'Click to enable this field' : 'Click to ignore this field'}
                        >
                          {field.disabled ? 'Off' : 'On'}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-muted-foreground">No parameters for this strategy</p>
                )}
              </div>
            )}

            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting || !selectedStrategy}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {mode === 'broker' ? 'Change Broker & Strategy' : 'Change Strategy'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
