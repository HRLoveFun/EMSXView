/**
 * ExecutionView standalone build config.
 *
 * Build: npx vite build --config vite.config.execution.ts
 * Output: dist/execution/
 */
import { defineConfig } from 'vite';
import { createModuleConfig } from './vite.base';

export default defineConfig(createModuleConfig({ moduleName: 'execution' }));
