/**
 * CostView standalone build config.
 *
 * Build: npx vite build --config vite.config.costview.ts
 * Output: dist/costview/
 */
import { defineConfig } from 'vite';
import { createModuleConfig } from './vite.base';

export default defineConfig(createModuleConfig({ moduleName: 'costview' }));
