/**
 * shell-less — minimal ShellContext provider for standalone module builds.
 *
 * When a module is built independently, the full AppShell is not present.
 * This provides stub implementations of shell services so the module
 * can render without a full shell wrapper.
 */
import { ShellContext } from '@shared/lib/shell-context';
import type { ShellContextValue } from '@shared/lib/shell-context';

function noop(): void {
  /* no-op in standalone mode */
}

const stubShell: ShellContextValue = {
  navigateTo: noop,
  addToast: (type, message) => {
    console.log(`[standalone toast] ${type}: ${message}`);
  },
  realtimeClient: null,
  streamConnected: false,
  streamEverConnected: false,
  subscriptionsWarming: false,
  subscriptionsWarmingMode: 'initial',
  logout: noop,
};

interface ShellLessProps {
  children: React.ReactNode;
}

export function ShellLessProvider({ children }: ShellLessProps) {
  return (
    <ShellContext.Provider value={stubShell}>
      {children}
    </ShellContext.Provider>
  );
}
