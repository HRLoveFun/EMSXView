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
        "@execution": path.resolve(__dirname, "./src/modules/execution"),
        "@costview": path.resolve(__dirname, "./src/modules/costview"),
        "@marketview": path.resolve(__dirname, "./src/modules/marketview"),
        "@databaseview": path.resolve(__dirname, "./src/modules/databaseview"),
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test-setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
    },
    server: {
      port: 5173,
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
            if (id.includes('/src/modules/databaseview/')) {
              return 'module-databaseview';
            }
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
              || id.includes('node_modules/cmdk/')
              || id.includes('node_modules/embla-carousel-react/')
              || id.includes('node_modules/input-otp/')
              || id.includes('node_modules/next-themes/')
              || id.includes('node_modules/react-day-picker/')
              || id.includes('node_modules/react-hook-form/')
              || id.includes('node_modules/react-resizable-panels/')
              || id.includes('node_modules/sonner/')
              || id.includes('node_modules/vaul/')
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
