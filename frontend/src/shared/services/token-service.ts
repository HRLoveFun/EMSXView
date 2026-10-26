/**
 * Token management service — shared across all frontend modules.
 *
 * NOTE: This is the canonical shared copy. The @execution/services/http-client module
 * re-exports tokenService from here for backward compatibility.
 */

const TOKEN_KEY = 'emsx_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * 读取当前 token 的角色（仅用于 UI 门控；权限边界仍由后端强制）。
 *
 * 只解码 JWT payload，不做验签——前端无法也不会替代后端鉴权。
 */
export function getTokenRole(): string | null {
  const token = getToken();
  if (!token) return null;
  const segment = token.split('.')[1];
  if (!segment) return null;
  try {
    const base64 = segment.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
    const payload = JSON.parse(atob(padded)) as { role?: unknown };
    return typeof payload.role === 'string' ? payload.role : null;
  } catch {
    return null;
  }
}

export const tokenService = {
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  getToken: () => getToken(),
  clearToken: () => localStorage.removeItem(TOKEN_KEY),
};
