import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Route } from '@execution/types';

interface ModifyLimitPriceDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route, limitPrice: number | null) => Promise<void>;
}

export function ModifyLimitPriceDialog({
  route, open, onOpenChange, onConfirm,
}: ModifyLimitPriceDialogProps) {
  const [limitPrice, setLimitPrice] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (route) setLimitPrice(route.limitPrice?.toString() || '');
  }, [route, open]);

  const handleConfirm = async () => {
    if (!route) return;
    setIsSubmitting(true);
    try {
      await onConfirm(route, limitPrice ? parseFloat(limitPrice) : null);
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
          <DialogDescription>Change the limit price for this route.</DialogDescription>
        </DialogHeader>
        {route && (
          <div className="space-y-4 py-4">
            <div className="text-sm bg-secondary/50 p-3 rounded">
              <span className="text-muted-foreground">Current Limit Price:</span>
              <div className="font-mono font-semibold">{route.limitPrice || 'Not set'}</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-limit-price">New Limit Price</Label>
              <Input id="new-limit-price" type="number" step="0.01" value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)} placeholder="Enter new limit price" />
              <p className="text-xs text-muted-foreground">Leave empty to clear the limit price</p>
            </div>
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
