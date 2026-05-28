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

export function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  return headers;
}

export const tokenService = {
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  getToken: () => getToken(),
  clearToken: () => localStorage.removeItem(TOKEN_KEY),
};
