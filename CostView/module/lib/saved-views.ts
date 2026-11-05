/** 命名筛选视图（Saved Views）——按作用域存储，带 schema 版本与损坏数据兜底。 */

const STORAGE_PREFIX = 'emsx_costview_saved_views_v1';
const MAX_VIEWS = 20;

export const SAVED_VIEWS_SCHEMA_VERSION = 1;

export interface SavedView<TState> {
  id: string;
  name: string;
  state: TState;
  createdAt: string;
  updatedAt: string;
}

interface StoredViews<TState> {
  version: number;
  views: SavedView<TState>[];
}

function storageKey(scope: string): string {
  return `${STORAGE_PREFIX}:${scope}`;
}

function isSavedView<TState>(value: unknown): value is SavedView<TState> {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<SavedView<TState>>;
  return typeof candidate.id === 'string'
    && typeof candidate.name === 'string'
    && candidate.state != null
    && typeof candidate.createdAt === 'string'
    && typeof candidate.updatedAt === 'string';
}

/** 读取某作用域的视图；版本不符或数据损坏时回退为空列表。 */
export function loadSavedViews<TState>(scope: string): SavedView<TState>[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(storageKey(scope));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return [];
    const stored = parsed as Partial<StoredViews<TState>>;
    if (stored.version !== SAVED_VIEWS_SCHEMA_VERSION || !Array.isArray(stored.views)) return [];
    return stored.views.filter((view): view is SavedView<TState> => isSavedView<TState>(view));
  } catch {
    return [];
  }
}

function persistSavedViews<TState>(scope: string, views: SavedView<TState>[]): void {
  if (typeof window === 'undefined') return;
  try {
    const payload: StoredViews<TState> = { version: SAVED_VIEWS_SCHEMA_VERSION, views };
    window.localStorage.setItem(storageKey(scope), JSON.stringify(payload));
  } catch {
    // 配额/隐私模式：保存失败不阻断筛选操作
  }
}

function createId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 新增或按名称覆盖一个视图，返回更新后的列表。 */
export function saveView<TState>(scope: string, name: string, state: TState): SavedView<TState>[] {
  const trimmed = name.trim();
  if (!trimmed) return loadSavedViews<TState>(scope);
  const now = new Date().toISOString();
  const views = loadSavedViews<TState>(scope);
  const existing = views.find((view) => view.name === trimmed);
  const next = existing
    ? views.map((view) => (view.id === existing.id
      ? { ...view, state, updatedAt: now }
      : view))
    : [...views, { id: createId(), name: trimmed, state, createdAt: now, updatedAt: now }];
  const capped = next.slice(-MAX_VIEWS);
  persistSavedViews(scope, capped);
  return capped;
}

/** 删除一个视图，返回更新后的列表。 */
export function deleteView<TState>(scope: string, id: string): SavedView<TState>[] {
  const next = loadSavedViews<TState>(scope).filter((view) => view.id !== id);
  persistSavedViews(scope, next);
  return next;
}
