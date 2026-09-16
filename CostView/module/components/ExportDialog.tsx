import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { CostViewConfig, ExportFormat, ExportScope } from '../types';

interface ExportDialogProps {
  config: CostViewConfig;
  isExporting: boolean;
  open: boolean;
  selectedOrderAvailable: boolean;
  onExport: (format: ExportFormat, scope: ExportScope) => Promise<boolean>;
  onOpenChange: (open: boolean) => void;
}

export function ExportDialog({ config, isExporting, open, selectedOrderAvailable, onExport, onOpenChange }: ExportDialogProps) {
  const [format, setFormat] = useState<ExportFormat>(config.exportDefaults.format);
  const [scope, setScope] = useState<ExportScope>(config.exportDefaults.scope);

  return (
    <Dialog key={open ? 'export-open' : 'export-closed'} open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Export CostView Report</DialogTitle>
          <DialogDescription>Select the export format and data scope.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Format</span>
            <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={format} onChange={(event) => setFormat(event.target.value as ExportFormat)}>
              <option value="csv">CSV</option>
              <option value="excel">Excel</option>
              <option value="pdf">PDF (print preview)</option>
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Scope</span>
            <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={scope} onChange={(event) => setScope(event.target.value as ExportScope)}>
              <option value="current-page">Current page</option>
              <option value="all-filtered">All filtered results</option>
              <option value="selected-order" disabled={!selectedOrderAvailable}>Selected route detail</option>
            </select>
          </label>
          <div className="rounded-lg border border-dashed border-border p-3 text-xs text-muted-foreground">
            CSV exports flat tabular data. Excel adds multi-sheet summary and thresholds. PDF opens a print-friendly report that can be saved as PDF from the browser.
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={async () => {
              const success = await onExport(format, scope);
              if (success) {
                onOpenChange(false);
              }
            }}
            disabled={isExporting || (scope === 'selected-order' && !selectedOrderAvailable)}
          >
            {isExporting ? 'Exporting…' : 'Export'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}