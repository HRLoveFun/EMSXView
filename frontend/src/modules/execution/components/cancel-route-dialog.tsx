import { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import type { Route } from '@execution/types';

interface CancelRouteDialogProps {
  route: Route | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (route: Route) => Promise<void>;
}

export function CancelRouteDialog({
  route, open, onOpenChange, onConfirm,
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
