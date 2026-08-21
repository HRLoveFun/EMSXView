/**
 * DatabaseView — standalone build entry point.
 *
 * Build: npx vite build --config vite.config.databaseview.ts
 * Output: dist/databaseview/
 */
/* eslint-disable react-refresh/only-export-components -- 独立构建入口，不适用 fast refresh */
import { StrictMode, Suspense, lazy } from 'react';
import { createRoot } from 'react-dom/client';
import '../../index.css';
import '../../modules/databaseview/module.registry';
import { moduleRegistry } from '@shared/lib/module-registry';
import { ShellLessProvider } from '../shell-less';

const desc = moduleRegistry.get('database')!;
const DatabaseViewModule = lazy(desc.loader);

function DatabaseViewStandaloneApp() {
  return (
    <div className="min-h-screen bg-background">
      <ShellLessProvider>
        <Suspense fallback={
          <div className="flex items-center justify-center min-h-screen text-muted-foreground">
            Loading Database View…
          </div>
        }>
          <DatabaseViewModule />
        </Suspense>
      </ShellLessProvider>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <DatabaseViewStandaloneApp />
  </StrictMode>,
);
