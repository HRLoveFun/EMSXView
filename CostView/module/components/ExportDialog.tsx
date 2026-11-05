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
import { SegmentedField, type SegmentedOption } from './SegmentedField';
import type { CostViewConfig, ExportFormat, ExportScope } from '../types';

const FORMAT_OPTIONS: Array<SegmentedOption<ExportFormat>> = [
  { value: 'csv', label: 'CSV' },
  { value: 'excel', label: 'Excel' },
  { value: 'pdf', label: 'PDF' },
];

const SCOPE_OPTIONS: Array<SegmentedOption<ExportScope>> = [
  { value: 'current-page', label: '当前页' },
  { value: 'all-filtered', label: '全部筛选' },
  { value: 'selected-order', label: '选中路由' },
];

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
          <div className="space-y-1 text-sm">
            <span className="text-muted-foreground">Format</span>
            <SegmentedField
              ariaLabel="Format"
              options={FORMAT_OPTIONS}
              value={format}
              onChange={(value) => setFormat(value as ExportFormat)}
              size="md"
            />
          </div>
          <div className="space-y-1 text-sm">
            <span className="text-muted-foreground">Scope</span>
            <SegmentedField
              ariaLabel="Scope"
              options={SCOPE_OPTIONS.map((option) => ({
                ...option,
                disabled: option.value === 'selected-order' && !selectedOrderAvailable,
              }))}
              value={scope}
              onChange={(value) => setScope(value as ExportScope)}
              size="md"
            />
            {!selectedOrderAvailable ? (
              <p className="text-xs text-muted-foreground">选中路由后才能导出单条明细。</p>
            ) : null}
          </div>
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