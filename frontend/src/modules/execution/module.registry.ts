/**
 * Execution module registration.
 *
 * Registers the Execution View module with the shell registry so the shell
 * can discover and render it without hardcoding module paths or IDs.
 */
import { moduleRegistry } from '@shared/lib/module-registry';
import type { ModuleDescriptor } from '@shared/lib/module-registry';

const descriptor: ModuleDescriptor = {
  id: 'execution',
  label: 'Execution View',
  order: 0,
  isDefault: true,
  loader: () => import('@execution/ExecutionModule'),
  // ExecutionModule is always loaded eagerly — no hover prefetch needed
};

moduleRegistry.register(descriptor);
