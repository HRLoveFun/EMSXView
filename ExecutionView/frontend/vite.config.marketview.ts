/**
 * MarketView standalone build config.
 *
 * Build: npx vite build --config vite.config.marketview.ts
 * Output: dist/marketview/
 */
import { defineConfig } from 'vite';
import { createModuleConfig } from './vite.base';

export default defineConfig(createModuleConfig({ moduleName: 'marketview' }));
