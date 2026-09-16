import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { BrokerSelectionPanelProps } from './types';

export function BrokerSelectionPanel({
  visibleBrokers,
  selectedBrokers,
  editable,
  toggleBroker,
}: BrokerSelectionPanelProps) {
  const allSelected = visibleBrokers.length > 0 &&
    visibleBrokers.every(b => selectedBrokers.includes(b));

  const handleToggleAll = () => {
    if (allSelected) {
      for (const b of visibleBrokers) {
        if (selectedBrokers.includes(b)) toggleBroker(b);
      }
    } else {
      for (const b of visibleBrokers) {
        if (!selectedBrokers.includes(b)) toggleBroker(b);
      }
    }
  };

  return (
    <div className="border border-border rounded p-3 bg-secondary/20 space-y-2">
      <div className="flex items-center gap-2">
        <Label className="text-xs">Brokers</Label>
        <span className="text-[11px] text-muted-foreground">
          {selectedBrokers.length === 0
            ? 'Pick one or more brokers \u2014 each becomes its own destination per order.'
            : `${selectedBrokers.length} broker${selectedBrokers.length === 1 ? '' : 's'} selected`}
        </span>
        {editable && visibleBrokers.length > 0 && (
          <div className="ml-auto flex gap-1">
            <button
              type="button"
              onClick={handleToggleAll}
              className="text-[11px] text-primary hover:underline"
              title={allSelected ? 'Deselect all brokers' : 'Select all brokers'}
            >
              {allSelected ? 'Deselect all' : 'Select all'}
            </button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {visibleBrokers.map(b => {
          const checked = selectedBrokers.includes(b);
          return (
            <label
              key={b}
              className={
                'inline-flex items-center gap-1.5 px-2 py-1 rounded border cursor-pointer text-xs select-none ' +
                (checked
                  ? 'bg-primary/15 border-primary/60'
                  : 'bg-background border-border hover:bg-accent')
              }
            >
              <Checkbox
                checked={checked}
                onCheckedChange={() => editable && toggleBroker(b)}
                disabled={!editable}
              />
              <span className="font-mono">{b}</span>
            </label>
          );
        })}
        {visibleBrokers.length === 0 && (
          <span className="text-xs text-muted-foreground">No brokers available.</span>
        )}
      </div>
    </div>
  );
}
