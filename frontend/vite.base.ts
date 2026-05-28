/**
 * Vite shared base config — used by both the main app build and standalone module builds.
 */
import path from 'path';
import react from '@vitejs/plugin-react';
import type { UserConfig } from 'vite';

export interface ModuleBuildOptions {
  /** Module name, used for output dir and HTML entry path. */
  moduleName: string;
  /** Optional: override output directory (defaults to dist/<moduleName>). */
  outDir?: string;
}

export function createModuleConfig(opts: ModuleBuildOptions): UserConfig {
  const moduleName = opts.moduleName;
  const outDir = opts.outDir ?? `dist/${moduleName}`;

  return {
    base: '/',
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@app': path.resolve(__dirname, './src/app'),
        '@shared': path.resolve(__dirname, './src/shared'),
        '@execution': path.resolve(__dirname, './src/modules/execution'),
        '@costview': path.resolve(__dirname, './src/modules/costview'),
        '@marketview': path.resolve(__dirname, './src/modules/marketview'),
        '@databaseview': path.resolve(__dirname, './src/modules/databaseview'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: process.env.VITE_API_URL || 'http://localhost:3000',
          changeOrigin: true,
          timeout: 600000,
          proxyTimeout: 600000,
        },
        '/ws': {
          target: (process.env.VITE_API_URL || 'http://localhost:3000').replace(/^http/, 'ws'),
          ws: true,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir,
      sourcemap: false,
      rollupOptions: {
        input: path.resolve(__dirname, `src/standalone/${moduleName}/index.html`),
        output: {
          manualChunks(id) {
            // Only split the specific module into its own chunk
            if (id.includes(`/src/modules/${moduleName}/`)) {
              return `module-${moduleName}`;
            }
            if (!id.includes('node_modules')) {
              return undefined;
            }
            if (id.includes('node_modules/react/') || id.includes('node_modules/react-dom/')) {
              return 'vendor-react';
            }
            if (id.includes('node_modules/@radix-ui/')) {
              return 'vendor-radix';
            }
            if (id.includes('node_modules/recharts/')) {
              return 'vendor-charts';
            }
            return 'vendor-misc';
          },
        },
      },
    },
  };
}
