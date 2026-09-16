/// <reference types="vitest/config" />
import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_API_URL || 'http://localhost:3000';
  const wsTarget = apiTarget.replace(/^http/, 'ws');

  return {
    base: '/',
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
        "@app": path.resolve(__dirname, "./src/app"),
        "@shared": path.resolve(__dirname, "./src/shared"),
        // ExecutionView 已独立为仓库根级目录（与 frontend 平级）
        "@execution": path.resolve(__dirname, "../ExecutionView/module"),
        "@costview": path.resolve(__dirname, "./src/modules/costview"),
        "@marketview": path.resolve(__dirname, "./src/modules/marketview"),
      },
      // npm workspaces 下依赖被提升到仓库根 node_modules；dedupe 确保
      // 无论从哪条路径解析，react / react-dom 都只取同一份实例
      dedupe: ['react', 'react-dom'],
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
      // ExecutionView 源码与测试位于仓库根级目录，需一并纳入收集范围
      include: ['src/**/*.test.{ts,tsx}', '../ExecutionView/**/*.test.{ts,tsx}'],
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
          target: apiTarget,
          changeOrigin: true,
          timeout: 600000,  // 600s (10 min) timeout for long pipeline/BDIB queries
          proxyTimeout: 600000,
        },
        '/ws': {
          target: wsTarget,
          ws: true,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            // ── App module chunks (keep lazy-loaded modules in dedicated bundles) ──
            // 010-extract-pipeline: databaseview 模块已迁独立项目，chunk 规则同步移除
            if (id.includes('/src/modules/costview/')) {
              return 'module-costview';
            }
            if (id.includes('/src/modules/marketview/')) {
              return 'module-marketview';
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
            if (id.includes('node_modules/lucide-react/')) {
              return 'vendor-icons';
            }
            if (id.includes('node_modules/recharts/')) {
              return 'vendor-charts';
            }
            if (
              id.includes('node_modules/class-variance-authority/')
              || id.includes('node_modules/clsx/')
              || id.includes('node_modules/tailwind-merge/')
              || id.includes('node_modules/zod/')
            ) {
              return 'vendor-ui';
            }
            return 'vendor-misc';
          },
        },
      },
    },
  };
});
