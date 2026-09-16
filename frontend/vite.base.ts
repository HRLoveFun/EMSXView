/**
 * Vite shared base config — used by both the main app build and standalone module builds.
 */
import path from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
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

/** 受支持的 standalone 模块清单（与 src/standalone/ 目录一一对应）。 */
const SUPPORTED_MODULES = ['execution', 'costview', 'marketview'] as const;

/**
 * 默认导出：供 `vite build --config vite.base.ts -- --module=<name>` 直接使用，
 * 模块名从命令行 argv 解析（不占用 --mode，保持 import.meta.env.MODE 原语义），
 * 替代原先每个模块一份样板配置文件（vite.config.<module>.ts）的方式。
 */
export default defineConfig(() => {
  // 从 argv 提取 --module=<name>（vite CLI 不识别该参数，故置于 -- 分隔符之后）
  const moduleArg = process.argv.find((arg) => arg.startsWith('--module='));
  const moduleName = moduleArg?.split('=')[1] ?? '';
  if (!(SUPPORTED_MODULES as readonly string[]).includes(moduleName)) {
    throw new Error(
      `[vite.base] 缺少或无效的 --module 参数，请使用 --module ${SUPPORTED_MODULES.join('|')}`,
    );
  }
  return createModuleConfig({ moduleName });
});
