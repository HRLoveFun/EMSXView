import { Filter } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

interface MultiSelectFilterPopoverProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (vals: string[]) => void;
  mode?: 'include' | 'exclude';
  onModeChange?: (mode: 'include' | 'exclude') => void;
}

export function MultiSelectFilterPopover({
  label,
  options,
  selected,
  onChange,
  mode,
  onModeChange,
}: MultiSelectFilterPopoverProps) {
  const active = selected.length > 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className={`inline-flex items-center ${active ? 'text-primary' : 'text-muted-foreground/50'}`}>
          <Filter className="h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-52 p-2" align="start">
        {onModeChange && (
          <div className="flex items-center gap-1 mb-2 p-1 bg-secondary/50 rounded">
            <button
              className={`flex-1 text-xs py-1 px-2 rounded ${mode === 'include' ? 'bg-primary text-primary-foreground' : 'hover:bg-secondary'}`}
              onClick={() => onModeChange('include')}
            >
              Include
            </button>
            <button
              className={`flex-1 text-xs py-1 px-2 rounded ${mode === 'exclude' ? 'bg-destructive text-destructive-foreground' : 'hover:bg-secondary'}`}
              onClick={() => onModeChange('exclude')}
            >
              Exclude
            </button>
          </div>
        )}
        <div className="space-y-1 max-h-52 overflow-y-auto">
          {options.length === 0 ? (
            <div className="px-1 py-2 text-xs text-muted-foreground">No {label} available</div>
          ) : (
            options.map(opt => (
              <label key={opt} className="flex items-center gap-2 px-1 py-0.5 text-xs cursor-pointer hover:bg-accent rounded">
                <Checkbox
                  checked={selected.includes(opt)}
                  onCheckedChange={(checked) => {
                    if (checked) onChange([...selected, opt]);
                    else onChange(selected.filter(x => x !== opt));
                  }}
                  className="h-3.5 w-3.5"
                />
                {opt}
              </label>
            ))
          )}
        </div>
        {active && (
          <button className="mt-2 w-full text-xs text-destructive hover:underline" onClick={() => onChange([])}>
            Clear
          </button>
        )}
      </PopoverContent>
    </Popover>
  );
}
