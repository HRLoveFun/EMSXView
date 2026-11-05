/** 最近使用值（筛选选项置顶）——按维度作用域分别存储，最多保留 6 个。 */

const STORAGE_KEY = 'emsx_costview_recent_filters_v1';
const MAX_RECENT = 6;

type RecentMap = Record<string, string[]>;

function readMap(): RecentMap {
  if (typeof window === 'undefined') return {};
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const entries = Object.entries(parsed as Record<string, unknown>)
      .filter((entry): entry is [string, string[]] => Array.isArray(entry[1]))
      .map(([scope, values]) => [scope, values.filter((value): value is string => typeof value === 'string')]);
    return Object.fromEntries(entries);
  } catch {
    return {};
  }
}

function writeMap(map: RecentMap): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // localStorage 不可用（隐私模式/配额）时静默降级：最近使用只是增强项
  }
}

/** 读取某维度的最近使用值（新→旧）。 */
export function loadRecentValues(scope: string): string[] {
  return readMap()[scope] ?? [];
}

/** 记录一次选择，返回更新后的列表。 */
export function recordRecentValue(scope: string, value: string): string[] {
  const trimmed = value.trim();
  if (!trimmed) return loadRecentValues(scope);
  const map = readMap();
  const next = [trimmed, ...(map[scope] ?? []).filter((item) => item !== trimmed)].slice(0, MAX_RECENT);
  map[scope] = next;
  writeMap(map);
  return next;
}

/** 清空某维度的最近使用记录。 */
export function clearRecentValues(scope: string): void {
  const map = readMap();
  delete map[scope];
  writeMap(map);
}
