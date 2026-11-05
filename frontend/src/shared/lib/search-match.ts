/**
 * 多关键词 AND 子串匹配（大小写不敏感）。
 * 查询按空白拆分，每个关键词都必须出现在 haystack 中；空查询视为匹配。
 */
export function matchesKeywords(query: string, haystack: string): boolean {
  const keywords = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!keywords.length) return true;
  const target = haystack.toLowerCase();
  return keywords.every((keyword) => target.includes(keyword));
}
