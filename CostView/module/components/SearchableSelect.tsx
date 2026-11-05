import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Check, ChevronDown, Search, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { matchesKeywords } from '@shared/lib/search-match';
import { cn } from '@shared/lib/utils';
import { loadRecentValues, recordRecentValue } from '../lib/recent-values';

interface SearchableSelectProps {
  label?: string;
  options: ReadonlyArray<string>;
  value: ReadonlyArray<string>;
  onChange: (values: string[]) => void;
  /** 默认多选；单选模式下选中后立即关闭 */
  multiple?: boolean;
  /** 允许把输入框里的任意文本作为值添加（如 Symbol） */
  allowCustom?: boolean;
  displayNames?: Record<string, string>;
  counts?: Record<string, number>;
  /** 传入作用域后，最近选择的值会在列表顶部置顶 */
  recentScope?: string;
  placeholder?: string;
  emptyLabel?: string;
  ariaLabel?: string;
  /** 选项网格列数（2–4），用于 Broker / Exchange 等长列表 */
  columns?: number;
  disabled?: boolean;
  className?: string;
  triggerClassName?: string;
}

interface OptionGroup {
  key: string;
  label: string;
  options: string[];
  start: number;
}

const MAX_HINT_ITEMS = 2;
/** 触发框下方最多展示的已选 chip 数，其余折叠为 +N */
const MAX_VISIBLE_CHIPS = 6;

function displayValue(value: string, displayNames?: Record<string, string>): string {
  return displayNames?.[value] ?? value;
}

function panelWidth(columns: number): string {
  if (columns >= 4) return 'w-[30rem]';
  if (columns === 3) return 'w-[26rem]';
  if (columns === 2) return 'w-[22rem]';
  return 'w-[22rem]';
}

/** 可搜索选择器：输入即过滤、↑↓/Enter 键盘选择、多选不关闭、已选 chip 可直接移除。 */
export function SearchableSelect({
  label,
  options,
  value,
  onChange,
  multiple = true,
  allowCustom = false,
  displayNames,
  counts,
  recentScope,
  placeholder,
  emptyLabel = '全部',
  ariaLabel,
  columns = 1,
  disabled = false,
  className,
  triggerClassName,
}: SearchableSelectProps) {
  const listId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  /** 用值而不是下标记录键盘光标：列表按「已选/最近」重排后光标不会漂移到别的项 */
  const [cursorValue, setCursorValue] = useState<string | null>(null);
  const [recent, setRecent] = useState<string[]>(() => (recentScope ? loadRecentValues(recentScope) : []));

  const selectedSet = useMemo(() => new Set(value), [value]);
  const recentSet = useMemo(() => new Set(recent), [recent]);
  const filtered = useMemo(
    () => options.filter((option) => matchesKeywords(query, `${option} ${displayNames?.[option] ?? ''}`)),
    [options, query, displayNames],
  );

  const ordered = useMemo(() => {
    const base = [...filtered].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    if (query.trim()) return base;
    const rank = (option: string) => (selectedSet.has(option) ? 0 : recentSet.has(option) ? 1 : 2);
    return base.sort((a, b) => rank(a) - rank(b));
  }, [filtered, query, selectedSet, recentSet]);

  const groups = useMemo<OptionGroup[]>(() => {
    if (query.trim()) return [{ key: 'match', label: `匹配 · ${ordered.length}`, options: ordered, start: 0 }];
    const selected = ordered.filter((option) => selectedSet.has(option));
    const recentOptions = ordered.filter((option) => !selectedSet.has(option) && recentSet.has(option));
    const rest = ordered.filter((option) => !selectedSet.has(option) && !recentSet.has(option));
    let start = 0;
    return [
      { key: 'selected', label: `已选 · ${selected.length}`, options: selected },
      { key: 'recent', label: '最近使用', options: recentOptions },
      { key: 'all', label: '全部', options: rest },
    ]
      .filter((group) => group.options.length > 0)
      .map((group) => {
        const withStart = { ...group, start };
        start += group.options.length;
        return withStart;
      });
  }, [ordered, query, selectedSet, recentSet]);

  const visibleOptions = groups.flatMap((group) => group.options);
  const cursor = cursorValue ? visibleOptions.indexOf(cursorValue) : -1;
  const trimmedQuery = query.trim();
  const customCandidate = allowCustom
    && trimmedQuery.length > 0
    && !options.some((option) => option.toLowerCase() === trimmedQuery.toLowerCase())
    && !selectedSet.has(trimmedQuery);
  const activeId = cursor >= 0 && cursor < visibleOptions.length
    ? `${listId}-option-${cursor}`
    : undefined;

  function remember(nextValue: string) {
    if (!recentScope) return;
    setRecent(recordRecentValue(recentScope, nextValue));
  }

  function toggle(rawValue: string) {
    const nextValue = rawValue.trim();
    if (!nextValue) return;
    if (!multiple) {
      onChange(selectedSet.has(nextValue) ? [] : [nextValue]);
      remember(nextValue);
      handleOpenChange(false);
      return;
    }
    if (selectedSet.has(nextValue)) {
      onChange(value.filter((item) => item !== nextValue));
      return;
    }
    onChange([...value, nextValue]);
    remember(nextValue);
  }

  function removeItem(nextValue: string) {
    onChange(value.filter((item) => item !== nextValue));
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    setQuery('');
    setCursorValue(null);
  }

  function moveCursor(delta: number) {
    const count = visibleOptions.length;
    if (!count) return;
    const current = cursorValue ? visibleOptions.indexOf(cursorValue) : -1;
    const next = current < 0
      ? (delta > 0 ? 0 : count - 1)
      : (current + delta + count) % count;
    setCursorValue(visibleOptions[next] ?? null);
  }

  function confirmCursor() {
    if (cursor >= 0 && visibleOptions[cursor]) {
      toggle(visibleOptions[cursor]);
      return;
    }
    if (!trimmedQuery) return;
    // 输入恰好等于某个已有选项时，直接按 Enter 应选中它，而不是要求先按 ↓
    const exact = options.find((option) => option.toLowerCase() === trimmedQuery.toLowerCase());
    if (exact) {
      toggle(exact);
      setQuery('');
      return;
    }
    if (customCandidate) {
      toggle(trimmedQuery);
      setQuery('');
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveCursor(1);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveCursor(-1);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      confirmCursor();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      handleOpenChange(false);
      return;
    }
    if (event.key === 'Backspace' && !query && multiple && value.length > 0) {
      event.preventDefault();
      onChange(value.slice(0, -1));
    }
  }

  function selectAllVisible() {
    const merged = new Set([...value, ...filtered]);
    onChange([...merged]);
  }

  function summary(): string {
    if (!value.length) return emptyLabel;
    if (!multiple) return displayValue(value[0], displayNames);
    const names = value.slice(0, MAX_HINT_ITEMS).map((item) => displayValue(item, displayNames));
    const extra = value.length > MAX_HINT_ITEMS ? ` +${value.length - MAX_HINT_ITEMS}` : '';
    return `${value.length} 项 · ${names.join(', ')}${extra}`;
  }

  function renderOption(option: string, index: number) {
    const selected = selectedSet.has(option);
    return (
      <div
        key={option}
        id={`${listId}-option-${index}`}
        role="option"
        aria-selected={selected}
        className={cn(
          'flex cursor-pointer items-center gap-2 rounded px-1.5 py-1.5 text-xs',
          index === cursor ? 'bg-accent' : 'hover:bg-accent',
        )}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => toggle(option)}
      >
        <span
          className={cn(
            'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border',
            selected ? 'border-primary bg-primary text-primary-foreground' : 'border-input',
          )}
        >
          {selected ? <Check className="h-2.5 w-2.5" /> : null}
        </span>
        <span className="min-w-0 flex-1 truncate">{displayValue(option, displayNames)}</span>
        {counts?.[option] != null ? (
          <span className="text-[10px] tabular-nums text-muted-foreground">{counts[option]}</span>
        ) : null}
      </div>
    );
  }

  function renderGroup(group: OptionGroup) {
    const gridStyle = columns > 1
      ? { display: 'grid', gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }
      : undefined;
    return (
      <div key={group.key} className="mb-1" role="group" aria-label={group.label}>
        <div className="px-1.5 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
          {group.label}
        </div>
        <div className="gap-x-2 gap-y-0.5" style={gridStyle}>
          {group.options.map((option, offset) => renderOption(option, group.start + offset))}
        </div>
      </div>
    );
  }

  return (
    <div className={cn('space-y-1', className)}>
      {label ? <div className="text-xs text-muted-foreground">{label}</div> : null}
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            aria-label={ariaLabel ?? label}
            aria-haspopup="listbox"
            aria-expanded={open}
            disabled={disabled}
            className={cn(
              'h-9 w-full min-w-36 justify-between gap-2 px-3 text-xs font-normal',
              triggerClassName,
            )}
          >
            <span className={cn('truncate', !value.length && 'text-muted-foreground')}>{summary()}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className={cn('p-2', panelWidth(columns))}
          align="start"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            inputRef.current?.focus();
          }}
        >
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              ref={inputRef}
              role="combobox"
              aria-label={`搜索${label ?? ''}`}
              aria-expanded={open}
              aria-controls={listId}
              aria-autocomplete="list"
              aria-activedescendant={activeId}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setCursorValue(null);
              }}
              onKeyDown={handleKeyDown}
              placeholder={placeholder ?? '输入搜索…'}
              className="h-8 pl-7 text-xs"
            />
          </div>
          <div id={listId} role="listbox" aria-multiselectable={multiple} className="mt-2 max-h-64 overflow-y-auto">
            {groups.length ? groups.map(renderGroup) : (
              <div className="px-2 py-3 text-center text-xs text-muted-foreground">无匹配选项</div>
            )}
            {customCandidate ? (
              <button
                type="button"
                className="mt-1 flex w-full items-center rounded px-1.5 py-1.5 text-left text-xs text-primary hover:bg-accent"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  toggle(trimmedQuery);
                  setQuery('');
                }}
              >
                添加自定义：{trimmedQuery}
              </button>
            ) : null}
          </div>
          <div className="mt-2 flex items-center gap-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
            <button type="button" className="text-primary hover:underline" onClick={selectAllVisible}>
              全选当前
            </button>
            <button type="button" className="text-primary hover:underline" onClick={() => onChange([])}>
              清空
            </button>
            <span className="ml-auto">↑↓ Enter Esc</span>
          </div>
        </PopoverContent>
      </Popover>
      {multiple && value.length > 0 ? (
        <div className="flex max-w-full flex-wrap gap-1">
          {value.slice(0, MAX_VISIBLE_CHIPS).map((item) => (
            <Badge key={item} variant="secondary" className="gap-1 pr-1 text-[10px]">
              <span className="max-w-32 truncate">{displayValue(item, displayNames)}</span>
              <button
                type="button"
                aria-label={`移除 ${item}`}
                className="text-muted-foreground hover:text-foreground"
                onClick={() => removeItem(item)}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          ))}
          {value.length > MAX_VISIBLE_CHIPS ? (
            <Badge variant="outline" className="text-[10px]" title={value.slice(MAX_VISIBLE_CHIPS).map((item) => displayValue(item, displayNames)).join(', ')}>
              还有 {value.length - MAX_VISIBLE_CHIPS} 项
            </Badge>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
