import { X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { cn } from '@shared/lib/utils';

export interface FilterSummaryChip {
  key: string;
  label: string;
  onRemove: () => void;
  /** 传入后点击 chip 正文可重新定位到对应筛选器 */
  onEdit?: () => void;
}

interface FilterSummaryBarProps {
  chips: FilterSummaryChip[];
  onClearAll?: () => void;
  emptyLabel?: string;
  className?: string;
}

/** 已选条件常驻条：让筛选口径始终可见，并可单个移除。 */
export function FilterSummaryBar({
  chips,
  onClearAll,
  emptyLabel = '未设置筛选（显示全部数据）',
  className,
}: FilterSummaryBarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5 border-t border-border pt-3', className)}>
      <span className="text-xs text-muted-foreground">已选：</span>
      {chips.length === 0 ? (
        <span className="text-xs text-muted-foreground/70">{emptyLabel}</span>
      ) : (
        <>
          {chips.map((chip) => (
            <Badge key={chip.key} variant="secondary" className="gap-1 pr-1 text-[11px]">
              {chip.onEdit ? (
                <button type="button" className="hover:underline" onClick={chip.onEdit}>
                  {chip.label}
                </button>
              ) : (
                <span>{chip.label}</span>
              )}
              <button
                type="button"
                aria-label={`移除 ${chip.label}`}
                className="text-muted-foreground hover:text-foreground"
                onClick={chip.onRemove}
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </Badge>
          ))}
          {onClearAll ? (
            <button
              type="button"
              className="ml-1 text-xs text-destructive hover:underline"
              onClick={onClearAll}
            >
              清空全部
            </button>
          ) : null}
        </>
      )}
    </div>
  );
}
