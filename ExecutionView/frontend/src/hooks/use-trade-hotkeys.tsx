/**
 * Keyboard flow for the Trade screen.
 *
 * Focus model:
 *  - Trade screen has three logical panes (cycled via Shift+Tab): orders,
 *    routes, inspector. A global cursor row is tracked per pane.
 *  - Hotkeys only fire when the user is NOT typing in a text input / textarea
 *    (so "/" search, "?" cheatsheet, etc., do not steal keystrokes mid-typing).
 */

import { useEffect, useRef, useState } from 'react';

export type TradePane = 'orders' | 'routes' | 'inspector';

export interface TradeHotkeyHandlers {
  /** Called when user presses J / ArrowDown. */
  onCursorDown?: (pane: TradePane) => void;
  /** Called when user presses K / ArrowUp. */
  onCursorUp?: (pane: TradePane) => void;
  /** Called when user presses Space. */
  onToggleSelect?: (pane: TradePane) => void;
  /** Called when user presses Enter. */
  onActivate?: (pane: TradePane) => void;
  /** Called when user presses N (new route on current order). */
  onNewRoute?: () => void;
  /** Called when user presses M (modify current route). */
  onModifyRoute?: () => void;
  /** Called when user presses X (cancel current route — require confirm). */
  onCancelRoute?: () => void;
  /** Called when user presses Esc. */
  onEscape?: () => void;
  /** Called when user presses "/" to focus search. */
  onFocusSearch?: () => void;
}

function isTypingTarget(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = t.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (t.isContentEditable) return true;
  return false;
}

export function useTradeHotkeys(
  enabled: boolean,
  activePane: TradePane,
  handlers: TradeHotkeyHandlers,
  onPaneChange?: (pane: TradePane) => void,
) {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const activePaneRef = useRef(activePane);
  activePaneRef.current = activePane;

  const [cheatsheetOpen, setCheatsheetOpen] = useState(false);

  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (e: KeyboardEvent) => {
      // Dialog-triggered keyboard should be blocked globally for hotkeys
      if (isTypingTarget(e)) {
        if (e.key === 'Escape') handlersRef.current.onEscape?.();
        return;
      }
      const pane = activePaneRef.current;
      const h = handlersRef.current;
      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          h.onCursorDown?.(pane); e.preventDefault(); break;
        case 'k':
        case 'ArrowUp':
          h.onCursorUp?.(pane); e.preventDefault(); break;
        case ' ':
          h.onToggleSelect?.(pane); e.preventDefault(); break;
        case 'Enter':
          h.onActivate?.(pane); break;
        case 'n':
        case 'N':
          h.onNewRoute?.(); break;
        case 'm':
        case 'M':
          h.onModifyRoute?.(); break;
        case 'x':
        case 'X':
          h.onCancelRoute?.(); break;
        case 'Escape':
          h.onEscape?.();
          setCheatsheetOpen(false);
          break;
        case '/':
          h.onFocusSearch?.(); e.preventDefault(); break;
        case '?':
          setCheatsheetOpen(v => !v); e.preventDefault(); break;
        default:
          // Shift+Tab cycles panes (handled via event.shiftKey + Tab)
          if (e.key === 'Tab' && e.shiftKey && onPaneChange) {
            const order: TradePane[] = ['orders', 'routes', 'inspector'];
            const i = order.indexOf(pane);
            onPaneChange(order[(i + 1) % order.length]);
            e.preventDefault();
          }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled, onPaneChange]);

  return { cheatsheetOpen, setCheatsheetOpen };
}

// ─── Cheatsheet overlay ──────────────────────────────────────────────────────

export interface HotkeyCheatsheetProps {
  open: boolean;
  onClose: () => void;
}

export function HotkeyCheatsheet({ open, onClose }: HotkeyCheatsheetProps) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
      role="dialog"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="bg-card border border-border rounded-lg shadow-xl p-6 max-w-lg w-full"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">Trade — Keyboard Shortcuts</h3>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-xs"
          >
            Esc to close
          </button>
        </div>
        <dl className="space-y-1 text-xs">
          {[
            ['J / ↓', 'Move cursor down in current pane'],
            ['K / ↑', 'Move cursor up in current pane'],
            ['Space', 'Toggle selection of cursor row'],
            ['Enter', 'Activate / open details'],
            ['N', 'New Route for cursor Order'],
            ['M', 'Modify cursor Route'],
            ['X', 'Cancel cursor Route (requires confirm dialog)'],
            ['Shift+Tab', 'Cycle focus: Orders → Routes → Inspector'],
            ['/', 'Focus Trade search'],
            ['Esc', 'Clear Route filter / close dialog'],
            ['?', 'Toggle this cheatsheet'],
          ].map(([k, desc]) => (
            <div key={k} className="grid grid-cols-[120px_1fr] gap-2">
              <kbd className="px-1.5 py-0.5 rounded bg-muted font-mono text-[10px] text-center">{k}</kbd>
              <span className="text-muted-foreground">{desc}</span>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
