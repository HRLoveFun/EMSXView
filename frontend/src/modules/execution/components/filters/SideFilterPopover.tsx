import { Filter } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

interface SideFilterPopoverProps {
  value: string;
  onChange: (value: string) => void;
}

const OPTIONS = [
  { value: '', label: 'All' },
  { value: 'BUY', label: 'Buy' },
  { value: 'SELL', label: 'Sell' },
] as const;

export function SideFilterPopover({ value, onChange }: SideFilterPopoverProps) {
  const active = value.length > 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className={`inline-flex items-center ${active ? 'text-primary' : 'text-muted-foreground/50'}`}>
          <Filter className="h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-28 p-1" align="start" side="bottom">
        {OPTIONS.map(({ value: v, label }) => (
          <div
            key={v || 'all'}
            className={`px-2 py-1 text-xs cursor-pointer rounded hover:bg-accent ${(value || '') === v ? 'font-semibold text-primary' : ''}`}
            onMouseDown={e => { e.preventDefault(); onChange(v); }}
          >
            {label}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}
