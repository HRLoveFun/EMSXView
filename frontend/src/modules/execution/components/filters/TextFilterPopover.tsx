import { Search, X, Filter } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

interface TextFilterPopoverProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}

export function TextFilterPopover({ value, onChange, placeholder }: TextFilterPopoverProps) {
  const active = value.length > 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button className={`inline-flex items-center ${active ? 'text-primary' : 'text-muted-foreground/50'}`}>
          <Filter className="h-3 w-3" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-44 p-2" align="start">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          <Input
            value={value}
            onChange={e => onChange(e.target.value)}
            placeholder={placeholder}
            className="pl-7 h-7 text-xs"
            autoFocus
          />
          {active && (
            <button className="absolute right-2 top-1/2 -translate-y-1/2" onClick={() => onChange('')}>
              <X className="h-3 w-3 text-muted-foreground" />
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
