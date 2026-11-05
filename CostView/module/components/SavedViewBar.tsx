import { useState } from 'react';
import { Bookmark, Check, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@shared/lib/utils';
import type { SavedView } from '../lib/saved-views';

interface SavedViewBarProps<TState> {
  views: SavedView<TState>[];
  activeId: string | null;
  onApply: (view: SavedView<TState>) => void;
  onSave: (name: string) => void;
  onDelete: (id: string) => void;
  label?: string;
}

/** 命名筛选视图条：一键切换整组筛选；保存命名后可在同一维度复用。 */
export function SavedViewBar<TState>({
  views,
  activeId,
  onApply,
  onSave,
  onDelete,
  label = '快捷视图',
}: SavedViewBarProps<TState>) {
  const [isNaming, setIsNaming] = useState(false);
  const [draft, setDraft] = useState('');

  function commit() {
    const name = draft.trim();
    if (!name) return;
    onSave(name);
    setDraft('');
    setIsNaming(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <Bookmark className="h-3 w-3" />
        {label}：
      </span>
      {views.map((view) => (
        <span
          key={view.id}
          className={cn(
            'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
            activeId === view.id
              ? 'border-primary/30 bg-primary/10 text-primary'
              : 'border-border bg-card text-muted-foreground',
          )}
        >
          <button type="button" className="hover:underline" onClick={() => onApply(view)}>
            {view.name}
          </button>
          <button
            type="button"
            aria-label={`删除视图 ${view.name}`}
            className="text-muted-foreground hover:text-destructive"
            onClick={() => onDelete(view.id)}
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </span>
      ))}
      {views.length === 0 ? (
        <span className="text-[11px] text-muted-foreground/70">保存常用组合，下次一键切换</span>
      ) : null}
      {isNaming ? (
        <span className="inline-flex items-center gap-1">
          <Input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                commit();
              } else if (event.key === 'Escape') {
                setIsNaming(false);
                setDraft('');
              }
            }}
            placeholder="视图名称，如 每日复盘"
            className="h-7 w-40 text-xs"
          />
          <Button type="button" variant="ghost" size="sm" className="h-7 px-2" aria-label="保存视图" onClick={commit}>
            <Check className="h-3.5 w-3.5" />
          </Button>
        </span>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-[11px]"
          onClick={() => setIsNaming(true)}
        >
          <Plus className="h-3 w-3" />
          保存当前筛选
        </Button>
      )}
    </div>
  );
}
