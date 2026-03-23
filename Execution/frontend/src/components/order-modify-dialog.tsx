import { useState, useEffect } from 'react';
import { Edit3, AlertTriangle, Loader2 } from 'lucide-react';
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

// ============================================================================
// Order Modify Dialog
// ============================================================================
interface OrderModifyDialogProps {
  order: Order | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (order: Order, updates: OrderUpdates) => Promise<void>;
}

export interface OrderUpdates {
  orderType?: OrderType;
  price?: number | null;
  quantity?: number;
  timeInForce?: TimeInForce;
  stopPrice?: number | null;
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

export function OrderModifyDialog({
  order,
  open,
  onOpenChange,
  onConfirm,
}: OrderModifyDialogProps) {
  const [updates, setUpdates] = useState<OrderUpdates>({});
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset form when order changes
  useEffect(() => {
    if (order) {
      setUpdates({
        orderType: order.orderType,
        price: order.price,
        quantity: order.quantity,
        timeInForce: order.timeInForce,
        stopPrice: order.stopPrice ?? null,
      });
      setError('');
    }
  }, [order, open]);

  const handleConfirm = async () => {
    if (!order) return;

    // Validate quantity
    if (updates.quantity !== undefined) {
      if (updates.quantity < order.filledQuantity) {
        setError(`New quantity must be at least the filled amount (${order.filledQuantity})`);
        return;
      }
      if (updates.quantity <= 0) {
        setError('Quantity must be greater than 0');
        return;
      }
    }

    // Validate limit price for limit orders
    if (updates.orderType === 'LIMIT' && (updates.price === null || updates.price === undefined)) {
      setError('Limit price is required for limit orders');
      return;
    }

    // Validate stop price for stop orders
    if ((updates.orderType === 'STOP' || updates.orderType === 'STOP_LIMIT') && 
        (updates.stopPrice === null || updates.stopPrice === undefined)) {
      setError('Stop price is required for stop orders');
      return;
    }

    setIsSubmitting(true);
    try {
      await onConfirm(order, updates);
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

  const showPriceField = updates.orderType === 'LIMIT' || updates.orderType === 'STOP_LIMIT';
  const showStopPriceField = updates.orderType === 'STOP' || updates.orderType === 'STOP_LIMIT';

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Edit3 className="h-5 w-5 text-primary" />
            Modify Order
          </DialogTitle>
          <DialogDescription>
            Modify order details. Only orders with status NEW, ASSIGNED, or WORKING can be modified.
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
                <span className="text-muted-foreground">Filled:</span>
                <span className="font-mono">{order.filledQuantity.toLocaleString()} / {order.quantity.toLocaleString()}</span>
              </div>
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Order Type */}
            <div className="space-y-2">
              <Label htmlFor="order-type">Order Type</Label>
              <Select
                value={updates.orderType}
                onValueChange={(v) => setUpdates({ ...updates, orderType: v as OrderType })}
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

            {/* Limit Price */}
            {showPriceField && (
              <div className="space-y-2">
                <Label htmlFor="limit-price">Limit Price</Label>
                <Input
                  id="limit-price"
                  type="number"
                  step="0.01"
                  min="0"
                  value={updates.price ?? ''}
                  onChange={(e) => setUpdates({ ...updates, price: e.target.value ? parseFloat(e.target.value) : null })}
                  placeholder="Enter limit price"
                />
                {order.price && (
                  <p className="text-xs text-muted-foreground">
                    Current: {order.price.toFixed(2)}
                  </p>
                )}
              </div>
            )}

            {/* Stop Price */}
            {showStopPriceField && (
              <div className="space-y-2">
                <Label htmlFor="stop-price">Stop Price</Label>
                <Input
                  id="stop-price"
                  type="number"
                  step="0.01"
                  min="0"
                  value={updates.stopPrice ?? ''}
                  onChange={(e) => setUpdates({ ...updates, stopPrice: e.target.value ? parseFloat(e.target.value) : null })}
                  placeholder="Enter stop price"
                />
                {order.stopPrice && (
                  <p className="text-xs text-muted-foreground">
                    Current: {order.stopPrice.toFixed(2)}
                  </p>
                )}
              </div>
            )}

            {/* Quantity */}
            <div className="space-y-2">
              <Label htmlFor="quantity">Quantity</Label>
              <Input
                id="quantity"
                type="number"
                min={order.filledQuantity}
                step="1"
                value={updates.quantity ?? ''}
                onChange={(e) => setUpdates({ ...updates, quantity: parseInt(e.target.value) || 0 })}
                placeholder="Enter quantity"
              />
              <p className="text-xs text-muted-foreground">
                Must be at least filled quantity ({order.filledQuantity.toLocaleString()})
              </p>
            </div>

            {/* Time in Force */}
            <div className="space-y-2">
              <Label htmlFor="tif">Time in Force</Label>
              <Select
                value={updates.timeInForce}
                onValueChange={(v) => setUpdates({ ...updates, timeInForce: v as TimeInForce })}
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
        )}

        <DialogFooter>
          <Button variant="outline" onClick={handleClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Apply Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
