import { useRef } from 'react';
import { CalendarDays } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from '@shared/lib/utils';

interface DateFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

/**
 * 日期输入框：点击输入框任意位置或右侧日历按钮都显式呼出原生选择器。
 *
 * 原生 `<input type="date">` 在各浏览器下交互不一致——点文本框通常只聚焦分段、
 * 只有点右侧小日历图标才弹日历，用户体感「时好时坏」。这里用 `showPicker()`
 * 把两种点击统一为「弹日历」；不支持该 API 的浏览器自动退回原生行为。
 */
export function DateField({ label, value, onChange, className }: DateFieldProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  // 不支持 showPicker() 的浏览器（旧 Safari/Firefox）：保留原生日历图标，收起自定义按钮，
  // 否则自定义按钮会盖住唯一能弹日历的原生入口。
  const supportsShowPicker = typeof HTMLInputElement !== 'undefined'
    && typeof HTMLInputElement.prototype.showPicker === 'function';

  const openPicker = () => {
    const input = inputRef.current;
    if (!input?.showPicker) return;
    try {
      input.showPicker();
    } catch {
      // 非用户手势 / 选择器已打开时浏览器可能抛错：静默退回原生交互
    }
  };

  return (
    <div className={cn('relative', className)}>
      <Input
        ref={inputRef}
        type="date"
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onClick={openPicker}
        className={cn('w-40', supportsShowPicker && 'pr-9 [&::-webkit-calendar-picker-indicator]:hidden')}
      />
      {supportsShowPicker ? (
        <button
          type="button"
          aria-label={`选择${label}`}
          title={`选择${label}`}
          onClick={openPicker}
          className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <CalendarDays className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
