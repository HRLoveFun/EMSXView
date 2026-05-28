/**
 * ExecutionView — standalone build entry point.
 *
 * Build: npx vite build --config vite.config.execution.ts
 * Output: dist/execution/
 */
import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import '../../index.css';
import '../../modules/execution/module.registry';
import { moduleRegistry } from '@shared/lib/module-registry';
import { ShellContext } from '@shared/lib/shell-context';
import type { ShellContextValue } from '@shared/lib/shell-context';

const desc = moduleRegistry.get('execution')!;
const ExecutionModule = lazy(desc.loader);

function noop() { /* no-op in standalone mode */ }

const stubShell: ShellContextValue = {
  navigateTo: noop as ShellContextValue['navigateTo'],
  addToast: ((type: string, message: string) => {
    console.log(`[standalone toast] ${type}: ${message}`);
  }) as ShellContextValue['addToast'],
  realtimeClient: null,
  streamConnected: false,
  streamEverConnected: false,
  subscriptionsWarming: false,
  subscriptionsWarmingMode: 'initial',
  logout: noop,
};

function ExecutionStandaloneApp() {
  return (
    <ShellContext.Provider value={stubShell}>
      <div className="min-h-screen bg-background">
        <Suspense fallback={
          <div className="flex items-center justify-center min-h-screen text-muted-foreground">
            Loading Execution View…
          </div>
        }>
          <ExecutionModule />
        </Suspense>
      </div>
    </ShellContext.Provider>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ExecutionStandaloneApp />
  </StrictMode>,
);
