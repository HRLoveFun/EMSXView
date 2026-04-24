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
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          timeout: 120000,  // 120s timeout for long Bloomberg requests
          proxyTimeout: 120000,
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
            if (!id.includes('node_modules')) {
              return undefined;
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
