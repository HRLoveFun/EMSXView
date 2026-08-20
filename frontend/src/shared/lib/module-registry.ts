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
      // 防护 (P2): 重复注册不再静默 — DEV 警告, 生产环境 error 级日志,
      // 便于发现模块更新未生效等注册问题
      const message = `[ModuleRegistry] Module "${descriptor.id}" is already registered — skipping duplicate.`;
      if (import.meta.env.DEV) {
        console.warn(message);
      } else {
        console.error(message);
      }
      return;
    }

    // 防护 (P2): realtimeWsPath 冲突检测 — 多个模块声明不同的 WS 路径时
    // shell 只会连接第一个, 其余被静默忽略。注册时即告警, 避免隐性失效。
    if (descriptor.realtimeWsPath) {
      const existing = this.findRealtimeDeclarations();
      if (existing.length > 0 && existing[0].realtimeWsPath !== descriptor.realtimeWsPath) {
        console.error(
          `[ModuleRegistry] realtimeWsPath conflict: "${descriptor.id}" declares ` +
          `"${descriptor.realtimeWsPath}" but "${existing[0].id}" already declares ` +
          `"${existing[0].realtimeWsPath}". Shell connects only to the first.`,
        );
      }
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

  /** Modules declaring a realtime WS path, sorted by `order`. */
  findRealtimeDeclarations(): ModuleDescriptor[] {
    return this.getAll().filter(m => m.realtimeWsPath);
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

  /**
   * 校验并安全切换激活模块 (防护 P2)。
   * 未注册 id 返回 null 且不改变状态 — 调用方应忽略 null 结果,
   * 避免渲染空白页 (旧行为: setActiveModule 直接透传任意字符串)。
   */
  navigateTo(id: ModuleId, current: ModuleId): ModuleId | null {
    if (!this.has(id)) {
      console.error(`[ModuleRegistry] navigateTo: unknown module id "${id}" (current: "${current}")`);
      return null;
    }
    return id;
  }
}

/** Singleton module registry — modules import to register, shell imports to query. */
export const moduleRegistry = new ModuleRegistry();
