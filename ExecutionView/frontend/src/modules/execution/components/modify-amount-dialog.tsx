import { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { Route } from '@execution/types';

interface ModifyAmountDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route, newAmount: number) => Promise<void>;
}

export function ModifyAmountDialog({
  route, open, onOpenChange, onConfirm,
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
                onChange={(e) => { setNewAmount(e.target.value); setError(''); }}
                min={route.filled}
                className={error ? 'border-destructive' : ''}
              />
              {error && <p className="text-xs text-destructive">{error}</p>}
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
