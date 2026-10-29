/**
 * 点击元素外部时触发回调（弹层/抽屉的「点空白处关闭」）。
 *
 * `ignoreSelector` 命中的点击不视为外部：常用于触发按钮，避免「mousedown 关闭、
 * click 又打开」的抖动，让按钮自己负责 toggle。
 */

import { useEffect, type RefObject } from 'react';

interface UseClickOutsideOptions {
  /** 为 false 时不监听（弹层未打开） */
  enabled?: boolean;
  /** 命中该选择器的元素视为「内部」，不触发关闭 */
  ignoreSelector?: string;
}

export function useClickOutside(
  ref: RefObject<HTMLElement | null>,
  onOutside: () => void,
  { enabled = true, ignoreSelector }: UseClickOutsideOptions = {},
): void {
  useEffect(() => {
    if (!enabled) return;
    const handle = (event: MouseEvent): void => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (ref.current?.contains(target)) return;
      if (ignoreSelector && target instanceof Element && target.closest(ignoreSelector)) return;
      onOutside();
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [enabled, ignoreSelector, onOutside, ref]);
}
