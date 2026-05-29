/**
 * Module Registry — lightweight discovery mechanism for workspace modules.
 *
 * Modules self-register via `moduleRegistry.register(...)` in their own
 * `module.registry.ts` files. The shell queries the registry to discover
 * available modules, render tabs, and load components — without importing
 * any module code directly.
 *
 * Usage:
 *   // In a module's module.registry.ts:
 *   import { moduleRegistry } from '@shared/lib/module-registry';
 *   moduleRegistry.register({ id: 'my-module', label: 'My Module', ... });
 *
 *   // In the shell:
 *   const modules = moduleRegistry.getAll();
 *   const defaultModule = moduleRegistry.getDefault();
 */

import type { ComponentType } from 'react';

// ── Types ──────────────────────────────────────────────────────────────────

/** Unique identifier for a workspace module. */
export type ModuleId = string;

/** Toolbar-facing info a module can contribute to the shell.
 *
 * ``counts`` holds domain-specific counters keyed by name (e.g.
 * ``{ orders: 42, routes: 7 }`` for the Execution module). Each module
 * populates the keys that are relevant to its domain.
 */
export interface ModuleContribution {
  /** Domain-specific counters (e.g. orders, routes, fills, etc.). */
  counts: Record<string, number>;
  isLoading: boolean;
  lastUpdatedAt: number | null;
  refresh: () => void;
  clearCache: () => void;
}

/** Props that every module component receives from the shell. */
export interface ModuleShellProps {
  /** Modules call this to push toolbar-relevant info to the shell. */
  onContribute?: (contribution: ModuleContribution) => void;
}

/** Descriptor that each module provides to register itself with the shell. */
export interface ModuleDescriptor {
  /** Unique module identifier (e.g. 'execution', 'costview'). */
  id: ModuleId;
  /** Human-readable label shown on the workspace tab. */
  label: string;
  /** Display order in the tab bar (lower = leftmost). */
  order: number;
  /** If true, this module is the active tab on initial load. */
  isDefault?: boolean;
  /** Dynamic import returning the module's root React component. */
  loader: () => Promise<{ default: ComponentType<any> }>;
  /** Optional hover-prefetch callback to warm the chunk cache. */
  prefetch?: () => void;
  /**
   * Optional WebSocket path for realtime data (e.g. '/ws/orders').
   * The shell creates and manages a single RealtimeClient for the first
   * module that declares this path. If no module declares a path, no
   * WebSocket connection is established.
   */
  realtimeWsPath?: string;
  /**
   * If true, the handoff badge (candidate count + recommendation count)
   * is rendered on this module's tab when pending handoffs exist.
   * Defaults to false. Only ExecutionView consumes handoffs currently.
   */
  showHandoffBadge?: boolean;
}

// ── Registry ───────────────────────────────────────────────────────────────

class ModuleRegistry {
  private readonly modules = new Map<ModuleId, ModuleDescriptor>();

  /** Register a module descriptor. Later registrations for the same id are ignored. */
  register(descriptor: ModuleDescriptor): void {
    if (this.modules.has(descriptor.id)) {
      if (import.meta.env.DEV) {
        console.warn(`[ModuleRegistry] Module "${descriptor.id}" is already registered — skipping duplicate.`);
      }
      return;
    }
    this.modules.set(descriptor.id, descriptor);
  }

  /** All registered modules, sorted by `order`. */
  getAll(): ModuleDescriptor[] {
    return Array.from(this.modules.values()).sort((a, b) => a.order - b.order);
  }

  /** Get all registered module IDs. */
  getAllIds(): ModuleId[] {
    return this.getAll().map(m => m.id);
  }

  /** Look up a module by id. */
  get(id: ModuleId): ModuleDescriptor | undefined {
    return this.modules.get(id);
  }

  /** The module marked as default, or the first module by order. */
  getDefault(): ModuleDescriptor | undefined {
    const all = this.getAll();
    return all.find(m => m.isDefault) ?? all[0];
  }

  /** Check if a module id is registered. */
  has(id: ModuleId): boolean {
    return this.modules.has(id);
  }
}

/** Singleton module registry — modules import to register, shell imports to query. */
export const moduleRegistry = new ModuleRegistry();
