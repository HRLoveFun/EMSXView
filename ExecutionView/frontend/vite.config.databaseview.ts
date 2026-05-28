/**
 * DatabaseView standalone build config.
 *
 * Build: npx vite build --config vite.config.databaseview.ts
 * Output: dist/databaseview/
 */
import { defineConfig } from 'vite';
import { createModuleConfig } from './vite.base';

export default defineConfig(createModuleConfig({ moduleName: 'database' }));
