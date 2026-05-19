import { useState, useEffect } from 'react';
import { Play, AlertTriangle, Loader2, Clock } from 'lucide-react';
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
import type {
  Order,
  ScheduleType,
  CreateParentExecutionRequest,
} from '@execution/types';

// ============================================================================
// Algo Launch Dialog
// ============================================================================

interface AlgoLaunchDialogProps {
  order: Order | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (request: CreateParentExecutionRequest) => Promise<void>;
}

const scheduleTypeOptions: { value: ScheduleType; label: string; description: string }[] = [
  { value: 'TWAP', label: 'TWAP', description: 'Time-Weighted Average Price — uniform distribution' },
  { value: 'VWAP', label: 'VWAP', description: 'Volume-Weighted Average Price — follows volume curve' },
  { value: 'POV', label: 'POV', description: 'Percentage of Volume — targets participation rate' },
];

const urgencyOptions = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'URGENT', label: 'Urgent' },
];

function defaultEndTime(): string {
  const d = new Date();
  d.setHours(16, 0, 0, 0);
  return d.toISOString().slice(0, 16);
}

function defaultStartTime(): string {
  const d = new Date();
  d.setMinutes(d.getMinutes() + 5);
  return d.toISOString().slice(0, 16);
}

export function AlgoLaunchDialog({
  order,
  open,
  onOpenChange,
  onConfirm,
}: AlgoLaunchDialogProps) {
  const [scheduleType, setScheduleType] = useState<ScheduleType>('TWAP');
  const [targetQuantity, setTargetQuantity] = useState(0);
  const [numSlices, setNumSlices] = useState(10);
  const [startTime, setStartTime] = useState(defaultStartTime());
  const [endTime, setEndTime] = useState(defaultEndTime());
  const [participationRate, setParticipationRate] = useState(10);
  const [urgency, setUrgency] = useState('MEDIUM');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset form when order changes
  useEffect(() => {
    if (order) {
      setTargetQuantity(order.remainingQuantity);
      setScheduleType('TWAP');
      setNumSlices(Math.min(Math.max(Math.ceil(order.remainingQuantity / 1000), 4), 100));
      setStartTime(defaultStartTime());
      setEndTime(defaultEndTime());
      setParticipationRate(10);
      setUrgency('MEDIUM');
      setError('');
    }
  }, [order, open]);

  const handleConfirm = async () => {
    if (!order) return;

    // Validation
    if (targetQuantity <= 0) {
      setError('Target quantity must be positive');
      return;
    }
    if (targetQuantity > order.remainingQuantity) {
      setError(`Target quantity exceeds remaining (${order.remainingQuantity})`);
      return;
    }
    if (numSlices <= 0) {
      setError('Number of slices must be positive');
      return;
    }
    const start = new Date(startTime);
    const end = new Date(endTime);
    if (end <= start) {
      setError('End time must be after start time');
      return;
    }
    if (scheduleType === 'POV' && (participationRate <= 0 || participationRate > 100)) {
      setError('Participation rate must be between 1-100%');
      return;
    }

    setError('');
    setIsSubmitting(true);

    try {
      const request: CreateParentExecutionRequest = {
        orderId: order.id,
        scheduleType,
        targetQuantity,
        numSlices,
        startTime: new Date(startTime).toISOString(),
        endTime: new Date(endTime).toISOString(),
        broker: order.broker || undefined,
        urgency,
      };

      if (scheduleType === 'POV') {
        request.participationRate = participationRate / 100;
      }

      await onConfirm(request);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to launch execution');
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!order) return null;

  const selectedTypeInfo = scheduleTypeOptions.find(o => o.value === scheduleType);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Play className="h-5 w-5" />
            Launch Algorithmic Execution
          </DialogTitle>
          <DialogDescription>
            Configure benchmark execution for{' '}
            <Badge variant="outline">{order.symbol}</Badge>{' '}
            — {order.remainingQuantity} shares remaining
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Schedule Type */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">Strategy</Label>
            <div className="col-span-3">
              <Select value={scheduleType} onValueChange={(v) => setScheduleType(v as ScheduleType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {scheduleTypeOptions.map(opt => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedTypeInfo && (
                <p className="text-xs text-muted-foreground mt-1">{selectedTypeInfo.description}</p>
              )}
            </div>
          </div>

          {/* Target Quantity */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">Quantity</Label>
            <Input
              type="number"
              value={targetQuantity}
              onChange={(e) => setTargetQuantity(Number(e.target.value))}
              className="col-span-3"
              min={1}
              max={order.remainingQuantity}
            />
          </div>

          {/* Number of Slices */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">Slices</Label>
            <Input
              type="number"
              value={numSlices}
              onChange={(e) => setNumSlices(Number(e.target.value))}
              className="col-span-3"
              min={1}
              max={1000}
            />
          </div>

          {/* Time Window */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right flex items-center gap-1">
              <Clock className="h-3 w-3" /> Start
            </Label>
            <Input
              type="datetime-local"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="col-span-3"
            />
          </div>
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right flex items-center gap-1">
              <Clock className="h-3 w-3" /> End
            </Label>
            <Input
              type="datetime-local"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="col-span-3"
            />
          </div>

          {/* POV Participation Rate */}
          {scheduleType === 'POV' && (
            <div className="grid grid-cols-4 items-center gap-4">
              <Label className="text-right">Part. Rate %</Label>
              <Input
                type="number"
                value={participationRate}
                onChange={(e) => setParticipationRate(Number(e.target.value))}
                className="col-span-3"
                min={1}
                max={100}
                step={1}
              />
            </div>
          )}

          {/* Urgency */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">Urgency</Label>
            <Select value={urgency} onValueChange={setUrgency}>
              <SelectTrigger className="col-span-3">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {urgencyOptions.map(opt => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Summary */}
          <div className="rounded-md bg-muted p-3 text-sm">
            <p className="font-medium mb-1">Schedule Preview</p>
            <p className="text-muted-foreground">
              {scheduleType} · {targetQuantity.toLocaleString()} shares ÷ {numSlices} slices
              = ~{Math.round(targetQuantity / numSlices).toLocaleString()} per slice
              {scheduleType === 'POV' && ` @ ${participationRate}% participation`}
            </p>
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Launching...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Launch Execution
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}