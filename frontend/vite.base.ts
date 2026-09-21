/**
 * Vite shared base config — used by both the main app build and standalone module builds.
 */
import path from 'path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import type { UserConfig } from 'vite';

export interface ModuleBuildOptions {
  /** Module name, used to resolve layout / output dir. */
  moduleName: string;
  /** Optional: override output directory (defaults to frontend/dist-modules/<moduleName>). */
  outDir?: string;
}

/**
 * 各 standalone 模块的目录布局（唯一真相源）。
 *
 * 三个业务模块均为仓库根级目录（与 `frontend/` 平级，见 docs/archive/2026-09-21/012-executionview-root-extract、
 * docs/archive/2026-09-21/018-costview-marketview-root-extract）：`ExecutionView/`、`CostView/`、`MarketView/`。
 * 故此处按模块登记「入口 HTML」与「模块 chunk 匹配串」，新增模块只需追加一行。
 */
interface ModuleLayout {
  /** 可选：vite root 覆盖（入口 HTML 不在 frontend/ 内时必填，否则 rollup 无法 emit 该 HTML）。 */
  root?: string;
  /** 入口 HTML（相对 root）。 */
  entry: string;
  /** 模块源码 chunk 匹配串（用于 manualChunks 独立分包）。 */
  chunkMatch: string;
}

const MODULE_LAYOUTS: Record<string, ModuleLayout> = {
  execution: {
    // 入口与源码均在仓库根级 ExecutionView/ 下，故 root 指向其 standalone 目录
    root: '../ExecutionView/standalone',
    entry: 'index.html',
    chunkMatch: '/ExecutionView/module/',
  },
  costview: {
    // 入口与源码均在仓库根级 CostView/ 下（与 ExecutionView 同构）
    root: '../CostView/standalone',
    entry: 'index.html',
    chunkMatch: '/CostView/module/',
  },
  marketview: {
    root: '../MarketView/standalone',
    entry: 'index.html',
    chunkMatch: '/MarketView/module/',
  },
};

/** 受支持的 standalone 模块清单（与 MODULE_LAYOUTS 一一对应）。 */
const SUPPORTED_MODULES = Object.keys(MODULE_LAYOUTS);

export function createModuleConfig(opts: ModuleBuildOptions): UserConfig {
  const moduleName = opts.moduleName;
  const layout = MODULE_LAYOUTS[moduleName];
  if (!layout) {
    throw new Error(
      `[vite.base] 未登记的 standalone 模块 "${moduleName}"，请在 MODULE_LAYOUTS 中登记`,
    );
  }
  // 入口不在 frontend/ 内时（如 ExecutionView/standalone）需把 vite root 指向入口所在目录，
  // 否则 rollup 会因「HTML 入口位于 root 之外」报 fileName must not be a relative path
  const moduleRoot = layout.root ? path.resolve(__dirname, layout.root) : __dirname;
  // 模块产物刻意与主应用 dist/ **分离**：主应用构建会清空自己的 outDir
  // （`npm run build` → frontend/dist），若模块产物落在 dist/<module>，
  // 先后执行两种构建时会被整体清掉（迁移前既有缺陷）
  const outDir = opts.outDir ?? path.resolve(__dirname, 'dist-modules', moduleName);

  return {
    root: moduleRoot,
    base: '/',
    plugins: [react()],
    css: {
      // root 可能被覆盖到 frontend/ 之外（如 ExecutionView/standalone），
      // 此时 postcss 向上查找不到 frontend/postcss.config.js（同级而非祖级），须显式指定
      postcss: path.resolve(__dirname, 'postcss.config.js'),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@app': path.resolve(__dirname, './src/app'),
        '@shared': path.resolve(__dirname, './src/shared'),
        // 三个业务模块均为仓库根级目录（与 frontend 平级）
        '@execution': path.resolve(__dirname, '../ExecutionView/module'),
        '@costview': path.resolve(__dirname, '../CostView/module'),
        '@marketview': path.resolve(__dirname, '../MarketView/module'),
      },
      // npm workspaces 下依赖被提升到仓库根 node_modules；dedupe 确保
      // 无论从哪条路径解析，react / react-dom 都只取同一份实例
      dedupe: ['react', 'react-dom'],
    },
    server: {
      port: 5173,
      fs: {
        // dev server 默认只服务 vite root（frontend/）内文件；
        // ExecutionView 位于其上级目录，需放行仓库根
        allow: [path.resolve(__dirname, '..')],
      },
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
      // root 被覆盖后 outDir 落在 root 之外，vite 默认不再清空 → 显式保持「每次构建清空」语义
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        input: path.resolve(moduleRoot, layout.entry),
        output: {
          manualChunks(id) {
            // Only split the specific module into its own chunk
            if (id.includes(layout.chunkMatch)) {
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

/**
 * 默认导出：供 `vite build --config vite.base.ts -- --module=<name>` 直接使用，
 * 模块名从命令行 argv 解析（不占用 --mode，保持 import.meta.env.MODE 原语义），
 * 替代原先每个模块一份样板配置文件（vite.config.<module>.ts）的方式。
 */
export default defineConfig(() => {
  // 从 argv 提取 --module=<name>（vite CLI 不识别该参数，故置于 -- 分隔符之后）
  const moduleArg = process.argv.find((arg) => arg.startsWith('--module='));
  const moduleName = moduleArg?.split('=')[1] ?? '';
  if (!SUPPORTED_MODULES.includes(moduleName)) {
    throw new Error(
      `[vite.base] 缺少或无效的 --module 参数，请使用 --module ${SUPPORTED_MODULES.join('|')}`,
    );
  }
  return createModuleConfig({ moduleName });
});
