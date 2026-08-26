import { useMemo, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

interface MultiSelectFilterProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
  displayNames?: Record<string, string>;
  /** 008: 选项按 N 列网格展示（市场/Broker 选项较多时降低纵向高度） */
  columns?: number;
}

/** 007: 多选下拉筛选（市场/Broker/Algo 通用）。选项统一按 A-Z 排列，支持多列展示。 */
export function MultiSelectFilter({
  label,
  options,
  selected,
  onChange,
  displayNames,
  columns = 1,
}: MultiSelectFilterProps) {
  const [open, setOpen] = useState(false);
  const active = selected.length > 0;

  // 008: 选项统一按字母序（A-Z，不区分大小写）排列
  const sortedOptions = useMemo(
    () => [...options].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' })),
    [options],
  );

  // 008: 多列展示时加宽下拉面板（静态类名保证 Tailwind JIT 可识别）
  const panelWidth = columns >= 4 ? 'w-[32rem]' : columns === 3 ? 'w-[26rem]' : columns === 2 ? 'w-80' : 'w-56';

  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <div className="space-y-1">
      <div className="text-xs capitalize text-muted-foreground">{label}</div>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            aria-label={label}
            className="h-9 w-40 justify-between gap-2 px-3 text-xs font-normal"
            type="button"
          >
            <span className="truncate">
              {active ? selected.map((v) => displayNames?.[v] ?? v).join(', ') : '全部'}
            </span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className={`${panelWidth} p-2`} align="start">
          {/* 批量操作：全选 / 反选（作用于当前全部选项） */}
          {sortedOptions.length > 0 && (
            <div className="mb-2 flex items-center gap-1 border-b border-border pb-2">
              <button
                type="button"
                className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                onClick={() => onChange([...sortedOptions])}
              >
                全选
              </button>
              <button
                type="button"
                className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                onClick={() => onChange(sortedOptions.filter((opt) => !selected.includes(opt)))}
              >
                反选
              </button>
            </div>
          )}
          <div
            className="max-h-64 gap-x-3 gap-y-1 overflow-y-auto pr-1"
            style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, columns)}, minmax(0, 1fr))` }}
          >
            {sortedOptions.length === 0 ? (
              <div className="px-1 py-2 text-xs text-muted-foreground">无可用选项</div>
            ) : (
              sortedOptions.map((opt) => (
                <label
                  key={opt}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-accent"
                >
                  <Checkbox
                    checked={selected.includes(opt)}
                    onCheckedChange={() => toggle(opt)}
                    className="h-3.5 w-3.5"
                  />
                  <span className="truncate">{displayNames?.[opt] ?? opt}</span>
                </label>
              ))
            )}
          </div>
          {active && (
            <div className="mt-2 flex flex-wrap gap-1 border-t border-border pt-2">
              {selected.slice(0, 3).map((v) => (
                <Badge key={v} variant="secondary" className="gap-1 pr-1 text-[10px]">
                  {displayNames?.[v] ?? v}
                  <button
                    type="button"
                    aria-label={`移除 ${v}`}
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => toggle(v)}
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </Badge>
              ))}
              {selected.length > 3 && (
                <Badge variant="secondary" className="text-[10px]">+{selected.length - 3}</Badge>
              )}
              <button
                type="button"
                className="ml-auto text-xs text-destructive hover:underline"
                onClick={() => onChange([])}
              >
                清空
              </button>
            </div>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
