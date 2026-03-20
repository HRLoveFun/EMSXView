import { useState } from 'react';
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
import type { UpdateableField, BatchUpdateRequest } from '@/types';

interface BatchOperationPanelProps {
  selectedCount: number;
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
  selectedCount, 
  onBatchUpdate, 
  onClearSelection,
  isLoading 
}: BatchOperationPanelProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedField, setSelectedField] = useState<UpdateableField>('price');
  const [newValue, setNewValue] = useState('');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

    if (!newValue && selectedField !== 'status') {
      setError('Please enter a value');
      return;
    }

    if (selectedField === 'price' || selectedField === 'quantity') {
      const numValue = parseFloat(newValue);
      if (isNaN(numValue) || numValue <= 0) {
        setError(`Invalid ${selectedField} value`);
        return;
      }
    }

    if (selectedField === 'status' && newValue === 'CANCELLED' && !confirmCancel) {
      setConfirmCancel(true);
      return;
    }

    // Get selected order IDs from parent
    const selectedOrderIds = Array.from(document.querySelectorAll('input[type="checkbox"]:checked'))
      .map(cb => (cb as HTMLInputElement).value)
      .filter(id => id.startsWith('ORD'));

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
              {selectedCount} order{selectedCount !== 1 ? 's' : ''} selected
            </span>
          </div>
          <Badge variant="secondary" className="text-xs">
            Ready for batch operation
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
            Clear
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
              Batch Modify Orders
            </DialogTitle>
            <DialogDescription>
              Modify {selectedCount} selected order{selectedCount !== 1 ? 's' : ''}
            </DialogDescription>
          </DialogHeader>

          {confirmCancel && (
            <Alert variant="destructive" className="mb-4">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                Are you sure you want to cancel these orders? This action cannot be undone.
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
                  Processing...
                </>
              ) : confirmCancel ? (
                <>
                  <Trash2 className="h-4 w-4 mr-2" />
                  Confirm Cancel
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
