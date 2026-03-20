import { useState, useEffect } from 'react';
import { GitBranch, AlertTriangle, Loader2 } from 'lucide-react';
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
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { Order, OrderType, TimeInForce } from '@/types';
import { useBrokerAlgorithms } from '@/hooks/use-broker-algorithms';
import { cachedApiService } from '@/services/api';

// ============================================================================
// Route Order Dialog
// ============================================================================
interface RouteOrderDialogProps {
  order: Order | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (order: Order, routeData: RouteOrderData) => Promise<void>;
}

export interface RouteOrderData {
  broker: string;
  strategy: string;
  quantity: number;
  orderType: OrderType;
  price?: number | null;
  stopPrice?: number | null;
  timeInForce: TimeInForce;
  exchangeDestination?: string;
  notes?: string;
}

const orderTypeOptions: { value: OrderType; label: string }[] = [
  { value: 'LIMIT', label: 'Limit' },
  { value: 'MARKET', label: 'Market' },
  { value: 'STOP', label: 'Stop' },
  { value: 'STOP_LIMIT', label: 'Stop Limit' },
];

const timeInForceOptions: { value: TimeInForce; label: string }[] = [
  { value: 'DAY', label: 'Day' },
  { value: 'GTC', label: 'Good Till Cancelled' },
  { value: 'IOC', label: 'Immediate or Cancel' },
  { value: 'FOK', label: 'Fill or Kill' },
];

export function RouteOrderDialog({
  order,
  open,
  onOpenChange,
  onConfirm,
}: RouteOrderDialogProps) {
  const [routeData, setRouteData] = useState<RouteOrderData>({
    broker: '',
    strategy: '',
    quantity: 0,
    orderType: 'LIMIT',
    price: null,
    stopPrice: null,
    timeInForce: 'DAY',
    exchangeDestination: '',
    notes: '',
  });
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [onDemandStrategies, setOnDemandStrategies] = useState<string[]>([]);
  const [isLoadingStrategies, setIsLoadingStrategies] = useState(false);
  
  const { configs, isLoading: isLoadingBrokers, getStrategiesForBroker, getParametersForStrategy } = useBrokerAlgorithms();

  // Get unique brokers from configs
  const availableBrokers = configs
    .map(c => c.broker)
    .filter((b, i, arr) => arr.indexOf(b) === i)
    .sort();

  // Get strategies for selected broker — prefer hook data, fall back to on-demand API
  const hookStrategies = routeData.broker
    ? getStrategiesForBroker(routeData.broker).map(s => s.name)
    : [];
  const availableStrategies = hookStrategies.length > 0 ? hookStrategies : onDemandStrategies;

  // On-demand strategy fetching when broker is selected but hook has no strategies
  useEffect(() => {
    if (!routeData.broker) {
      setOnDemandStrategies([]);
      return;
    }
    const hookStrats = getStrategiesForBroker(routeData.broker);
    if (hookStrats.length > 0) {
      setOnDemandStrategies([]);
      return;
    }
    // Fetch strategies on-demand from API
    let cancelled = false;
    setIsLoadingStrategies(true);
    cachedApiService.getBrokerStrategies(routeData.broker).then(res => {
      if (!cancelled && res.success && res.data?.strategies) {
        setOnDemandStrategies(res.data.strategies);
      }
    }).catch(() => { /* ignore */ }).finally(() => {
      if (!cancelled) setIsLoadingStrategies(false);
    });
    return () => { cancelled = true; };
  }, [routeData.broker, getStrategiesForBroker]);

  // Get parameters for selected strategy
  const strategyParams = routeData.broker && routeData.strategy
    ? getParametersForStrategy(routeData.broker, routeData.strategy)
    : [];

  // Reset form when order changes
  useEffect(() => {
    if (order) {
      setRouteData({
        broker: order.broker || '',
        strategy: '',
        quantity: order.remainingQuantity,
        orderType: order.orderType,
        price: order.price,
        stopPrice: order.stopPrice ?? null,
        timeInForce: order.timeInForce,
        exchangeDestination: order.exchange || '',
        notes: '',
      });
      setError('');
    }
  }, [order, open]);

  const handleConfirm = async () => {
    if (!order) return;

    // Validation
    if (!routeData.broker) {
      setError('Please select a broker');
      return;
    }

    if (routeData.quantity <= 0) {
      setError('Quantity must be greater than 0');
      return;
    }

    if (routeData.quantity > order.remainingQuantity) {
      setError(`Quantity cannot exceed remaining quantity (${order.remainingQuantity})`);
      return;
    }

    if (routeData.orderType === 'LIMIT' && (routeData.price === null || routeData.price <= 0)) {
      setError('Limit price is required for limit orders');
      return;
    }

    if ((routeData.orderType === 'STOP' || routeData.orderType === 'STOP_LIMIT') && 
        (routeData.stopPrice === null || routeData.stopPrice <= 0)) {
      setError('Stop price is required for stop orders');
      return;
    }

    setIsSubmitting(true);
    try {
      await onConfirm(order, routeData);
      onOpenChange(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      onOpenChange(false);
    }
  };

  const showPriceField = routeData.orderType === 'LIMIT' || routeData.orderType === 'STOP_LIMIT';
  const showStopPriceField = routeData.orderType === 'STOP' || routeData.orderType === 'STOP_LIMIT';

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            Route Order
          </DialogTitle>
          <DialogDescription>
            Create a child route for this order. The route will be sent to the selected broker for execution.
          </DialogDescription>
        </DialogHeader>

        {order && (
          <div className="space-y-4 py-4">
            {/* Order Summary */}
            <div className="bg-secondary/50 p-3 rounded text-sm space-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Order ID:</span>
                <span className="font-mono font-semibold">{order.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Ticker:</span>
                <span className="font-semibold">{order.symbol}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Side:</span>
                <span className={order.side === 'BUY' ? 'text-green-500 font-semibold' : 'text-red-500 font-semibold'}>
                  {order.side}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status:</span>
                <Badge variant="outline" className="text-xs">{order.status}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Available Qty:</span>
                <span className="font-mono">{order.remainingQuantity.toLocaleString()}</span>
              </div>
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="grid grid-cols-2 gap-4">
              {/* Broker Selection */}
              <div className="space-y-2">
                <Label htmlFor="broker">Broker *</Label>
                <Select
                  value={routeData.broker}
                  onValueChange={(v) => setRouteData({ ...routeData, broker: v, strategy: '' })}
                >
                  <SelectTrigger id="broker">
                    <SelectValue placeholder="Select broker" />
                  </SelectTrigger>
                  <SelectContent>
                    {isLoadingBrokers ? (
                      <SelectItem value="loading" disabled>Loading brokers...</SelectItem>
                    ) : availableBrokers.length > 0 ? (
                      availableBrokers.map((broker) => (
                        <SelectItem key={broker} value={broker}>
                          {broker}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="none" disabled>No brokers available</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              {/* Strategy Selection */}
              <div className="space-y-2">
                <Label htmlFor="strategy">Strategy</Label>
                <Select
                  value={routeData.strategy}
                  onValueChange={(v) => setRouteData({ ...routeData, strategy: v })}
                  disabled={!routeData.broker || (availableStrategies.length === 0 && !isLoadingStrategies)}
                >
                  <SelectTrigger id="strategy">
                    <SelectValue placeholder={
                      !routeData.broker ? 'Select broker first' :
                      isLoadingStrategies ? 'Loading strategies...' :
                      'Select strategy'
                    } />
                  </SelectTrigger>
                  <SelectContent>
                    {isLoadingStrategies ? (
                      <SelectItem value="loading" disabled>Loading strategies...</SelectItem>
                    ) : availableStrategies.length > 0 ? (
                      availableStrategies.map((strategy) => (
                        <SelectItem key={strategy} value={strategy}>
                          {strategy}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="none" disabled>No strategies available</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Algorithm Parameters (read-only summary) */}
            {strategyParams.length > 0 && (
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">Algorithm Parameters</Label>
                <div className="bg-muted/30 border rounded-md p-2 max-h-[120px] overflow-y-auto">
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                    {strategyParams.map((p) => (
                      <div key={p.fieldName} className="flex justify-between gap-2">
                        <span className="text-muted-foreground truncate">{p.fieldName}</span>
                        <span className="font-mono shrink-0">{p.stringValue || '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-4">
              {/* Route Quantity */}
              <div className="space-y-2">
                <Label htmlFor="quantity">Route Quantity *</Label>
                <Input
                  id="quantity"
                  type="number"
                  min={1}
                  max={order?.remainingQuantity}
                  step="1"
                  value={routeData.quantity || ''}
                  onChange={(e) => setRouteData({ ...routeData, quantity: parseInt(e.target.value) || 0 })}
                  placeholder="Enter quantity"
                />
              </div>

              {/* Order Type */}
              <div className="space-y-2">
                <Label htmlFor="order-type">Order Type *</Label>
                <Select
                  value={routeData.orderType}
                  onValueChange={(v) => setRouteData({ ...routeData, orderType: v as OrderType })}
                >
                  <SelectTrigger id="order-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {orderTypeOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Time in Force */}
              <div className="space-y-2">
                <Label htmlFor="tif">Time in Force *</Label>
                <Select
                  value={routeData.timeInForce}
                  onValueChange={(v) => setRouteData({ ...routeData, timeInForce: v as TimeInForce })}
                >
                  <SelectTrigger id="tif">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {timeInForceOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Limit Price */}
            {showPriceField && (
              <div className="space-y-2">
                <Label htmlFor="limit-price">Limit Price *</Label>
                <Input
                  id="limit-price"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={routeData.price ?? ''}
                  onChange={(e) => setRouteData({ ...routeData, price: e.target.value ? parseFloat(e.target.value) : null })}
                  placeholder="Enter limit price"
                />
                {order?.price && (
                  <p className="text-xs text-muted-foreground">
                    Order price: {order.price.toFixed(2)}
                  </p>
                )}
              </div>
            )}

            {/* Stop Price */}
            {showStopPriceField && (
              <div className="space-y-2">
                <Label htmlFor="stop-price">Stop Price *</Label>
                <Input
                  id="stop-price"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={routeData.stopPrice ?? ''}
                  onChange={(e) => setRouteData({ ...routeData, stopPrice: e.target.value ? parseFloat(e.target.value) : null })}
                  placeholder="Enter stop price"
                />
              </div>
            )}

            {/* Exchange Destination */}
            <div className="space-y-2">
              <Label htmlFor="exchange-destination">Exchange Destination</Label>
              <Input
                id="exchange-destination"
                value={routeData.exchangeDestination}
                onChange={(e) => setRouteData({ ...routeData, exchangeDestination: e.target.value })}
                placeholder="e.g., NYSE, NASDAQ, BATS"
              />
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <Label htmlFor="notes">Route Notes</Label>
              <Input
                id="notes"
                value={routeData.notes}
                onChange={(e) => setRouteData({ ...routeData, notes: e.target.value })}
                placeholder="Optional notes for this route"
              />
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create Route
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
