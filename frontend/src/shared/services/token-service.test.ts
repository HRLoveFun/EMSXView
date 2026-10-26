import { beforeEach, describe, expect, it } from 'vitest';

import { getTokenRole, tokenService } from './token-service';

function tokenWith(payload: Record<string, unknown>): string {
  const encode = (value: unknown): string =>
    btoa(JSON.stringify(value))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode(payload)}.signature`;
}

describe('getTokenRole', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('读取 JWT payload 中的角色', () => {
    tokenService.setToken(tokenWith({ sub: 'u1', role: 'admin' }));
    expect(getTokenRole()).toBe('admin');
  });

  it('没有 token 时返回 null', () => {
    expect(getTokenRole()).toBeNull();
  });

  it('格式错误时返回 null（不抛异常）', () => {
    tokenService.setToken('not-a-jwt');
    expect(getTokenRole()).toBeNull();
  });

  it('payload 缺 role 时返回 null', () => {
    tokenService.setToken(tokenWith({ sub: 'u1' }));
    expect(getTokenRole()).toBeNull();
  });
});
