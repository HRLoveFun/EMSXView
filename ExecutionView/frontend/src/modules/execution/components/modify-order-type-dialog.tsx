import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { Route } from '@execution/types';

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
  route, open, onOpenChange, onConfirm,
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
      await onConfirm(route, orderType, limitPrice ? parseFloat(limitPrice) : null, stopPrice ? parseFloat(stopPrice) : null, tif);
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
          <DialogDescription>Change the order type and related parameters.</DialogDescription>
        </DialogHeader>
        {route && (
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Order Type</Label>
              <Select value={orderType} onValueChange={setOrderType}>
                <SelectTrigger><SelectValue placeholder="Select order type" /></SelectTrigger>
                <SelectContent>
                  {ORDER_TYPES.map((type) => (
                    <SelectItem key={type.value} value={type.value}>{type.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Time In Force</Label>
              <Select value={tif} onValueChange={setTif}>
                <SelectTrigger><SelectValue placeholder="Select TIF" /></SelectTrigger>
                <SelectContent>
                  {TIF_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {showLimitPrice && (
              <div className="space-y-2">
                <Label htmlFor="limit-price">Limit Price</Label>
                <Input id="limit-price" type="number" step="0.01" value={limitPrice}
                  onChange={(e) => { setLimitPrice(e.target.value); setError(''); }}
                  placeholder="Enter limit price" />
              </div>
            )}
            {showStopPrice && (
              <div className="space-y-2">
                <Label htmlFor="stop-price">Stop Price</Label>
                <Input id="stop-price" type="number" step="0.01" value={stopPrice}
                  onChange={(e) => { setStopPrice(e.target.value); setError(''); }}
                  placeholder="Enter stop price" />
              </div>
            )}
            {error && <p className="text-xs text-destructive">{error}</p>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>Cancel</Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
