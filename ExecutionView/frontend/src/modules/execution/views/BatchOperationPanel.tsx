import { useState, useMemo } from 'react';
import { Edit3, Trash2, X, CheckSquare, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { UpdateableField, BatchUpdateRequest, Order } from '@execution/types'

interface BatchOperationPanelProps {
  /** Authoritative list of currently-selected order IDs. Replaces the previous
   *  DOM-scraping approach which silently truncated the batch when rows were
   *  virtualised, collapsed, or off-screen — and which also relied on a
   *  hard-coded `id.startsWith('ORD')` filter that excluded all real Bloomberg
   *  numeric sequences. */
  selectedOrderIds: string[];
  /** Optional: surfaced in the cancel-confirmation dialog so users see exactly
   *  which tickers / sides they are about to cancel before committing. */
  selectedOrders?: Order[];
  onBatchUpdate: (request: BatchUpdateRequest) => Promise<void>;
  onClearSelection: () => void;
  isLoading: boolean;
}

const updateableFields: { value: UpdateableField; label: string; type: 'number' | 'text' | 'select' }[] = [
  { value: 'price', label: 'Limit Price', type: 'number' },
  { value: 'quantity', label: 'Order Quantity', type: 'number' },
  { value: 'timeInForce', label: 'Time in Force', type: 'select' },
  { value: 'status', label: 'Order Status', type: 'select' },
];

const timeInForceOptions = [
  { value: 'DAY', label: 'Day' },
  { value: 'GTC', label: 'Good Till Cancelled' },
  { value: 'IOC', label: 'Immediate or Cancel' },
  { value: 'FOK', label: 'Fill or Kill' },
];

export function BatchOperationPanel({
  selectedOrderIds,
  selectedOrders = [],
  onBatchUpdate,
  onClearSelection,
  isLoading
}: BatchOperationPanelProps) {
  const selectedCount = selectedOrderIds.length;
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedField, setSelectedField] = useState<UpdateableField>('price');
  const [newValue, setNewValue] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Build a human-readable summary for the cancel confirmation: distinct
  // tickers + side breakdown so the trader knows exactly the blast radius
  // before signing off on an irreversible action.
  const cancelSummary = useMemo(() => {
    const tickers = new Set<string>();
    let buys = 0;
    let sells = 0;
    for (const o of selectedOrders) {
      if (o.symbol) tickers.add(o.symbol);
      if (o.side === 'BUY') buys += 1;
      else if (o.side === 'SELL') sells += 1;
    }
    const tickerList = Array.from(tickers);
    return {
      tickerCount: tickerList.length,
      sample: tickerList.slice(0, 5).join(', '),
      hasMore: tickerList.length > 5,
      buys,
      sells,
    };
  }, [selectedOrders]);

  const handleOpenModal = () => {
    setSelectedField('price');
    setNewValue('');
    setConfirmCancel(false);
    setError(null);
    setIsModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsModalOpen(false);
    setError(null);
  };

  const handleSubmit = async () => {
    setError(null);

    if (selectedOrderIds.length === 0) {
      setError('No orders are currently selected. Tick at least one order in the table first.');
      return;
    }

    if (!newValue && selectedField !== 'status') {
      setError('Please enter a value');
      return;
    }

    if (selectedField === 'price' || selectedField === 'quantity') {
      const numValue = parseFloat(newValue);
      // Guard zero / negative *first* so users typing "0" get the obvious
      // ">0" message instead of the misleading "must be at least filled (0)"
      // that was previously emitted when filledQuantity happened to be 0.
      if (isNaN(numValue)) {
        setError(`Invalid ${selectedField} value`);
        return;
      }
      if (numValue <= 0) {
        setError(`${selectedField === 'price' ? 'Limit price' : 'Quantity'} must be greater than 0`);
        return;
      }
    }

    if (selectedField === 'status' && newValue === 'CANCELLED' && !confirmCancel) {
      setConfirmCancel(true);
      return;
    }

    await onBatchUpdate({
      orderIds: selectedOrderIds,
      field: selectedField,
      value: newValue,
    });

    handleCloseModal();
  };

  const getFieldConfig = () => {
    return updateableFields.find(f => f.value === selectedField);
  };

  const renderValueInput = () => {
    const config = getFieldConfig();
    
    if (selectedField === 'timeInForce') {
      return (
        <Select value={newValue} onValueChange={setNewValue}>
          <SelectTrigger>
            <SelectValue placeholder="Select Time in Force" />
          </SelectTrigger>
          <SelectContent>
            {timeInForceOptions.map(option => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }

    if (selectedField === 'status') {
      return (
        <Select value={newValue} onValueChange={setNewValue}>
          <SelectTrigger>
            <SelectValue placeholder="Select Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="CANCELLED">Cancel Orders</SelectItem>
          </SelectContent>
        </Select>
      );
    }

    return (
      <Input
        type={config?.type === 'number' ? 'number' : 'text'}
        placeholder={`Enter new ${config?.label.toLowerCase()}`}
        value={newValue}
        onChange={(e) => setNewValue(e.target.value)}
        step={selectedField === 'price' ? '0.01' : '1'}
        min="0"
      />
    );
  };

  if (selectedCount === 0) {
    return null;
  }

  return (
    <>
      <div className="batch-panel">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <CheckSquare className="h-5 w-5 text-primary" />
            <span className="font-medium">
              {selectedCount} order{selectedCount === 1 ? '' : 's'} selected
            </span>
          </div>
          <Badge variant="secondary" className="text-xs">
            Batch actions available
          </Badge>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onClearSelection}
            disabled={isLoading}
          >
            <X className="h-4 w-4 mr-1.5" />
            Clear selection
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handleOpenModal}
            disabled={isLoading}
            className="gap-1.5"
          >
            <Edit3 className="h-4 w-4" />
            Batch Modify
          </Button>
        </div>
      </div>

      <Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit3 className="h-5 w-5" />
              Batch Modify
            </DialogTitle>
            <DialogDescription>
              Modify {selectedCount} selected order{selectedCount === 1 ? '' : 's'}
            </DialogDescription>
          </DialogHeader>

          {confirmCancel && (
            <Alert variant="destructive" className="mb-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                <div className="font-semibold">
                  About to cancel {selectedCount} order{selectedCount === 1 ? '' : 's'}
                  {cancelSummary.tickerCount > 0
                    ? `, across ${cancelSummary.tickerCount} ticker${cancelSummary.tickerCount === 1 ? '' : 's'}`
                    : ''}
                </div>
                {cancelSummary.tickerCount > 0 && (
                  <div className="mt-1 text-xs opacity-90">
                    {cancelSummary.buys > 0 && <>Buy × {cancelSummary.buys}</>}
                    {cancelSummary.buys > 0 && cancelSummary.sells > 0 && ' · '}
                    {cancelSummary.sells > 0 && <>Sell × {cancelSummary.sells}</>}
                    {cancelSummary.sample && (
                      <> · {cancelSummary.sample}{cancelSummary.hasMore ? ' …' : ''}</>
                    )}
                  </div>
                )}
                <div className="mt-1 text-xs">This action cannot be undone. Please confirm.</div>
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive" className="mb-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Field to Modify</Label>
              <Select value={selectedField} onValueChange={(v) => {
                setSelectedField(v as UpdateableField);
                setNewValue('');
                setConfirmCancel(false);
                setError(null);
              }}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {updateableFields.map(field => (
                    <SelectItem key={field.value} value={field.value}>
                      {field.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>New Value</Label>
              {renderValueInput()}
            </div>

            {selectedField === 'price' && (
              <p className="text-xs text-muted-foreground">
                This will update the limit price for all selected orders.
              </p>
            )}
            {selectedField === 'quantity' && (
              <p className="text-xs text-muted-foreground">
                New quantity must be greater than or equal to filled quantity.
              </p>
            )}
          </div>

          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={handleCloseModal} disabled={isLoading}>
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={isLoading}
              variant={confirmCancel ? 'destructive' : 'default'}
            >
              {isLoading ? (
                <>
                  <div className="spinner h-4 w-4 mr-2" />
                  Processing…
                </>
              ) : confirmCancel ? (
                <>
                  <Trash2 className="h-4 w-4 mr-2" />
                  Confirm Cancel {selectedCount} Order{selectedCount === 1 ? '' : 's'}
                </>
              ) : (
                <>
                  <CheckSquare className="h-4 w-4 mr-2" />
                  Apply Changes
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}