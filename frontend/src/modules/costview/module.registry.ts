/**
 * CostView module registration.
 */
import { moduleRegistry } from '@shared/lib/module-registry';
import type { ModuleDescriptor } from '@shared/lib/module-registry';

const descriptor: ModuleDescriptor = {
  id: 'costview',
  label: 'Cost View',
  order: 20,
  loader: () => import('@/modules/costview/CostViewModule'),
};

moduleRegistry.register(descriptor);
