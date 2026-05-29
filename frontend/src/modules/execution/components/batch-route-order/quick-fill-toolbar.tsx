import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { QUICK_PCT_PRESETS } from './types';
import type { QuickFillToolbarProps } from './types';

export function QuickFillToolbar({
  editable,
  selectedBrokers,
  selectedOrders,
  customPct,
  onCustomPctChange,
  onApplyPercentQty,
}: QuickFillToolbarProps) {
  const disabled = !editable || selectedBrokers.length === 0 || selectedOrders.length === 0;

  return (
    <div className="flex flex-wrap items-center gap-2 px-2 py-1.5 bg-secondary/30 border border-border rounded text-xs">
      <span className="text-muted-foreground">Quick-fill qty:</span>
      {QUICK_PCT_PRESETS.map(pct => (
        <Button
          key={pct}
          variant="outline"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={() => onApplyPercentQty(pct)}
          disabled={disabled}
          title={`Set each selected order's total qty to ${pct}% of its remaining, then split equally across the chosen brokers (lot-rounded).`}
        >
          {pct}%
        </Button>
      ))}
      <Input
        type="number"
        min={1}
        max={100}
        step={1}
        value={customPct}
        onChange={e => {
          const v = e.target.value;
          if (v === '') { onCustomPctChange(''); return; }
          const n = Number(v);
          if (!Number.isFinite(n)) return;
          onCustomPctChange(String(Math.max(1, Math.min(100, Math.round(n)))));
        }}
        onWheel={e => e.currentTarget.blur()}
        className="h-6 w-16 text-xs"
        disabled={disabled}
        title="Custom percentage (1\u2013100)"
      />
      <Button
        variant="outline"
        size="sm"
        className="h-6 px-2 text-xs"
        onClick={() => onApplyPercentQty(Number(customPct))}
        disabled={disabled}
      >
        Apply %
      </Button>
      <span className="ml-auto text-muted-foreground/70">
        Each qty cell is editable. Cells turn red on odd-lot or row over-allocation.
      </span>
    </div>
  );
}
