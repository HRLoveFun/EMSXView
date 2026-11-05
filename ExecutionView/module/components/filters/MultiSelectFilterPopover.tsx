import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Filter, Search } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

interface MultiSelectFilterPopoverProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (vals: string[]) => void;
  mode?: 'include' | 'exclude';
  onModeChange?: (mode: 'include' | 'exclude') => void;
  /** 值 → 展示名（如 status 枚举 → 友好标签） */
  displayNames?: Record<string, string>;
  /** 顶部增加「All」行，点击清空全部选择 */
  showAll?: boolean;
  triggerClassName?: string;
}

/** 表头列筛选：支持搜索、↑↓/Enter 键盘勾选、已选置顶与「全选当前」 */
export function MultiSelectFilterPopover({
  label,
  options,
  selected,
  onChange,
  mode,
  onModeChange,
  displayNames,
  showAll = false,
  triggerClassName,
}: MultiSelectFilterPopoverProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(-1);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const active = selected.length > 0;

  const visible = useMemo(() => {
    const keywords = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const matched = options.filter((option) => {
      const haystack = `${option} ${displayNames?.[option] ?? ''}`.toLowerCase();
      return keywords.every((keyword) => haystack.includes(keyword));
    });
    return matched.sort((a, b) => {
      const rank = (option: string) => (selectedSet.has(option) ? 0 : 1);
      return rank(a) - rank(b) || a.localeCompare(b, undefined, { sensitivity: 'base' });
    });
  }, [options, query, selectedSet, displayNames]);

  function toggle(option: string) {
    if (selectedSet.has(option)) onChange(selected.filter((item) => item !== option));
    else onChange([...selected, option]);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    setQuery('');
    setCursor(-1);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setCursor((current) => (visible.length ? (current + 1) % visible.length : -1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor((current) => (visible.length ? (current - 1 + visible.length) % visible.length : -1));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (visible[cursor]) toggle(visible[cursor]);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      handleOpenChange(false);
    } else if (event.key === 'Backspace' && !query && selected.length > 0) {
      event.preventDefault();
      onChange(selected.slice(0, -1));
    }
  }

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${label} 筛选`}
          onClick={(event) => event.stopPropagation()}
          className={`inline-flex items-center gap-0.5 ${triggerClassName ?? (active ? 'text-primary' : 'text-muted-foreground/50')}`}
        >
          <Filter className="h-3 w-3" />
          {active ? <span className="text-[9px] tabular-nums">{selected.length}</span> : null}
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-56 p-2"
        align="start"
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          inputRef.current?.focus();
        }}
      >
        {onModeChange && (
          <div className="mb-2 flex items-center gap-1 rounded bg-secondary/50 p-1">
            <button
              type="button"
              className={`flex-1 rounded px-2 py-1 text-xs ${mode === 'include' ? 'bg-primary text-primary-foreground' : 'hover:bg-secondary'}`}
              onClick={() => onModeChange('include')}
            >
              Include
            </button>
            <button
              type="button"
              className={`flex-1 rounded px-2 py-1 text-xs ${mode === 'exclude' ? 'bg-destructive text-destructive-foreground' : 'hover:bg-secondary'}`}
              onClick={() => onModeChange('exclude')}
            >
              Exclude
            </button>
          </div>
        )}
        <div className="relative mb-2">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            role="combobox"
            aria-label={`搜索 ${label}`}
            aria-expanded={open}
            aria-autocomplete="list"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(-1);
            }}
            onKeyDown={handleKeyDown}
            placeholder={`搜索 ${label}…`}
            className="h-7 pl-7 text-xs"
          />
        </div>
        {showAll ? (
          <label className="mb-1 flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-accent">
            <Checkbox checked={!active} onCheckedChange={() => onChange([])} className="h-3.5 w-3.5" />
            <span className="font-medium text-muted-foreground">All</span>
          </label>
        ) : null}
        <div role="listbox" aria-multiselectable className="max-h-52 space-y-1 overflow-y-auto">
          {visible.length === 0 ? (
            <div className="px-1 py-2 text-xs text-muted-foreground">
              {options.length === 0 ? `No ${label} available` : '无匹配选项'}
            </div>
          ) : (
            visible.map((option, index) => (
              <label
                key={option}
                className={`flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs ${index === cursor ? 'bg-accent' : 'hover:bg-accent'}`}
              >
                <Checkbox
                  checked={selectedSet.has(option)}
                  onCheckedChange={() => toggle(option)}
                  className="h-3.5 w-3.5"
                />
                <span className="truncate">{displayNames?.[option] ?? option}</span>
              </label>
            ))
          )}
        </div>
        <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
          <button
            type="button"
            className="text-primary hover:underline"
            onClick={() => onChange([...new Set([...selected, ...visible])])}
          >
            全选当前
          </button>
          {active ? (
            <button type="button" className="text-destructive hover:underline" onClick={() => onChange([])}>
              Clear
            </button>
          ) : null}
          <span className="ml-auto">↑↓ Enter</span>
        </div>
      </PopoverContent>
    </Popover>
  );
}
