import { cn } from '@shared/lib/utils';

export interface SegmentedOption<TValue extends string = string> {
  value: TValue;
  label: string;
  title?: string;
  disabled?: boolean;
}

interface SegmentedFieldProps<TValue extends string> {
  label?: string;
  options: ReadonlyArray<SegmentedOption<TValue>>;
  value: TValue | TValue[];
  onChange: (value: TValue | TValue[]) => void;
  /** 多选模式下可同时选中多个值；单选模式点击即替换 */
  multiple?: boolean;
  /** 多选模式下的清空项（如「全部」），点击后回调空数组 */
  clearValue?: TValue;
  ariaLabel?: string;
  size?: 'sm' | 'md';
  className?: string;
}

/** 2–6 个短枚举的平铺切换控件：一次点击完成切换，避免「展开下拉再选值」。 */
export function SegmentedField<TValue extends string>({
  label,
  options,
  value,
  onChange,
  multiple = false,
  clearValue,
  ariaLabel,
  size = 'sm',
  className,
}: SegmentedFieldProps<TValue>) {
  const selected = new Set<TValue>(Array.isArray(value) ? value : [value]);

  function isSelected(option: SegmentedOption<TValue>): boolean {
    if (multiple && clearValue !== undefined && option.value === clearValue) {
      return selected.size === 0;
    }
    return selected.has(option.value);
  }

  function handleClick(option: SegmentedOption<TValue>) {
    if (option.disabled) return;
    if (!multiple) {
      onChange(option.value);
      return;
    }
    if (clearValue !== undefined && option.value === clearValue) {
      onChange([]);
      return;
    }
    const current = Array.isArray(value) ? value : [];
    onChange(current.includes(option.value)
      ? current.filter((item) => item !== option.value)
      : [...current, option.value]);
  }

  return (
    <div className={cn('space-y-1', className)}>
      {label ? <span className="text-xs text-muted-foreground">{label}</span> : null}
      <div
        role="group"
        aria-label={ariaLabel ?? label}
        className={cn(
          'inline-flex max-w-full flex-wrap items-center gap-0.5 rounded-lg border border-border bg-muted/30 p-0.5',
          size === 'sm' ? 'text-xs' : 'text-sm',
        )}
      >
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={isSelected(option)}
            title={option.title}
            disabled={option.disabled}
            onClick={() => handleClick(option)}
            className={cn(
              'whitespace-nowrap rounded-md px-2.5 font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
              size === 'sm' ? 'py-1.5' : 'py-2',
              isSelected(option)
                ? 'bg-card text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
