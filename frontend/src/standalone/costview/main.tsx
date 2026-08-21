/**
 * CostView — standalone build entry point.
 *
 * Build: npx vite build --config vite.config.costview.ts
 * Output: dist/costview/
 */
/* eslint-disable react-refresh/only-export-components -- 独立构建入口，不适用 fast refresh */
import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import '../../index.css';
import '../../modules/costview/module.registry';
import { moduleRegistry } from '@shared/lib/module-registry';
import { ShellLessProvider } from '../shell-less';

const desc = moduleRegistry.get('costview')!;
const CostViewModule = lazy(desc.loader);

function CostViewStandaloneApp() {
  return (
    <div className="min-h-screen bg-background">
      <ShellLessProvider>
        <Suspense fallback={
          <div className="flex items-center justify-center min-h-screen text-muted-foreground">
            Loading Cost View…
          </div>
        }>
          <CostViewModule />
        </Suspense>
      </ShellLessProvider>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <CostViewStandaloneApp />
  </StrictMode>,
);
