/**
 * DatabaseView module registration.
 */
import { moduleRegistry } from '@shared/lib/module-registry';
import type { ModuleDescriptor } from '@shared/lib/module-registry';

const descriptor: ModuleDescriptor = {
  id: 'database',
  label: 'Database',
  order: 30,
  loader: () => import('@/modules/databaseview/DatabaseViewModule'),
};

moduleRegistry.register(descriptor);
