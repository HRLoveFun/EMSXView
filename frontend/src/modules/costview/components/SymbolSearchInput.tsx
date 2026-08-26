import { useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';

interface SymbolSearchInputProps {
  label: string;
  options: string[];
  selected: string[];
  onChange: (values: string[]) => void;
}

/** 最多展示的建议条数 */
const MAX_SUGGESTIONS = 8;

/** 008: Symbol 搜索输入框——输入即过滤建议、回车或点击添加、已选以 chip 展示（无下拉弹层） */
export function SymbolSearchInput({ label, options, selected, onChange }: SymbolSearchInputProps) {
  const [query, setQuery] = useState('');
  const [focused, setFocused] = useState(false);
  const rawQuery = query.trim();

  // 008: 按空白拆分多关键词（如 "aapl us" → ["aapl", "us"]），实现部分匹配
  const keywords = useMemo(
    () => rawQuery.toLowerCase().split(/\s+/).filter(Boolean),
    [rawQuery],
  );

  // 候选列表：字母序 + 排除已选 + 多关键词 AND 部分匹配（不区分大小写）
  const suggestions = useMemo(() => {
    const sorted = [...options].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    const filtered = sorted.filter((opt) => !selected.includes(opt));
    if (keywords.length === 0) return filtered.slice(0, MAX_SUGGESTIONS);
    return filtered
      .filter((opt) => {
        const lower = opt.toLowerCase();
        return keywords.every((kw) => lower.includes(kw));
      })
      .slice(0, MAX_SUGGESTIONS);
  }, [options, keywords, selected]);

  // 当前输入不在任何选项/已选中时，允许作为自定义值添加
  const canAddCustom =
    rawQuery.length > 0 &&
    !options.some((opt) => opt.toLowerCase() === rawQuery.toLowerCase()) &&
    !selected.some((s) => s.toLowerCase() === rawQuery.toLowerCase());

  const addValue = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || selected.includes(trimmed)) return;
    onChange([...selected, trimmed]);
    setQuery('');
  };

  const removeValue = (value: string) => onChange(selected.filter((v) => v !== value));

  return (
    <div className="space-y-1">
      <div className="text-xs capitalize text-muted-foreground">{label}</div>
      <div className="relative">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && query.trim()) {
              event.preventDefault();
              addValue(query);
            }
          }}
          placeholder="搜索 Symbol…"
          className="h-9 w-44 pl-7 text-xs"
        />
        {focused && query.trim() && (
          <div className="absolute z-10 mt-1 w-44 rounded-md border border-border bg-popover p-1 shadow-md">
            {suggestions.length === 0 ? (
              canAddCustom ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    addValue(query);
                  }}
                >
                  <span className="truncate">添加自定义：{query.trim()}</span>
                </button>
              ) : (
                <div className="px-2 py-1.5 text-xs text-muted-foreground">无匹配选项</div>
              )
            ) : (
              suggestions.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    addValue(opt);
                  }}
                >
                  <span className="truncate">{opt}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
      {selected.length > 0 && (
        <div className="flex max-w-44 flex-wrap gap-1">
          {selected.map((v) => (
            <Badge key={v} variant="secondary" className="gap-1 pr-1 text-[10px]">
              {v}
              <button
                type="button"
                aria-label={`移除 ${v}`}
                className="text-muted-foreground hover:text-foreground"
                onClick={() => removeValue(v)}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
