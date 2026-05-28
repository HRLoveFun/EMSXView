/**
 * MarketView module registration.
 */
import { moduleRegistry } from '@shared/lib/module-registry';
import type { ModuleDescriptor } from '@shared/lib/module-registry';

const descriptor: ModuleDescriptor = {
  id: 'marketview',
  label: 'Market View',
  order: 10,
  loader: () => import('@/modules/marketview/MarketViewModule'),
};

moduleRegistry.register(descriptor);
