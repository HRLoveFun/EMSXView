/**
 * useBrokerParamFields — 券商参数字段注册表（057 DL-16 收尾 / 220）。
 *
 * 单一真相源在后端 `GET /api/broker-param-fields`；本模块只做：
 * 1. 模块级缓存（同一次会话只请求一次；失败后下次挂载重试）；
 * 2. React 绑定（registry 未就绪时返回 null，调用方必须显式降级，不得静默猜字段名）；
 * 3. 纯查询函数（时间字段优先级、volume cap 归一匹配、整数上限券商）。
 *
 * 迁移前这些数据写死在 `data/broker-time-mapping.ts` 与
 * `data/broker-volume-cap-mapping.ts`，两处已随本 PR 删除。
 */

import { useEffect, useState } from 'react';
import { brokerApi } from '@execution/services/broker-api';
import type { BrokerParamFields, TimeFieldNames } from '@execution/types';

let cached: BrokerParamFields | null = null;
let inflight: Promise<BrokerParamFields | null> | null = null;

/** 拉取注册表（有缓存直接返回；并发调用共享同一个请求）。 */
export async function loadBrokerParamFields(): Promise<BrokerParamFields | null> {
  if (cached) return cached;
  if (!inflight) {
    inflight = brokerApi
      .getBrokerParamFields()
      .then(res => {
        if (res.success && res.data) {
          cached = res.data;
          return cached;
        }
        return null;
      })
      .catch(() => null)
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** 测试/登出用：清空模块级缓存。 */
export function resetBrokerParamFieldsCache(): void {
  cached = null;
  inflight = null;
}

export interface BrokerParamFieldsState {
  registry: BrokerParamFields | null;
  error: string;
}

export function useBrokerParamFields(): BrokerParamFieldsState {
  const [registry, setRegistry] = useState<BrokerParamFields | null>(cached);
  const [error, setError] = useState('');

  useEffect(() => {
    if (cached) return;
    let cancelled = false;
    loadBrokerParamFields().then(data => {
      if (cancelled) return;
      if (data) {
        setRegistry(data);
      } else {
        setError(
          'Broker parameter registry unavailable; time/volume-cap auto-fill is disabled.',
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return { registry, error };
}

// ── 纯查询函数（registry 必须已加载；未加载时返回空值） ──────────────────────

/** 起止时间字段：券商×策略覆盖优先，其次券商默认。 */
export function timeFieldsFor(
  registry: BrokerParamFields,
  broker: string,
  strategy: string,
): TimeFieldNames {
  const override = registry.timeFieldOverrides[broker]?.[strategy];
  if (override) return override;
  return registry.timeFields[broker] ?? { start: '', end: '' };
}

/** volume cap 本地覆盖（设置页维护；与注册表同键格式，按券商×策略覆盖）。 */
export const VOLUME_CAP_OVERRIDES_STORAGE_KEY = 'emsx_volume_cap_mapping_overrides';

function readVolumeCapOverrides(): Record<string, Record<string, string>> {
  try {
    if (typeof localStorage === 'undefined') return {};
    const raw = localStorage.getItem(VOLUME_CAP_OVERRIDES_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

/** volume cap 字段名：本地覆盖优先，其次注册表（策略名归一后匹配，`*` 兜底）。 */
export function volumeCapFieldFor(
  registry: BrokerParamFields,
  broker: string,
  strategy: string,
): string {
  const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
  const normalized = strategy ? norm(strategy) : '';
  const matchKey = (map: Record<string, string>): string | undefined => {
    if (!normalized) return undefined;
    const key = Object.keys(map).find(k => norm(k) === normalized);
    return key === undefined ? undefined : map[key];
  };

  const overrideMap = readVolumeCapOverrides()[broker];
  if (overrideMap) {
    const override = matchKey(overrideMap);
    if (override !== undefined) return override;
  }

  const brokerMap = registry.volumeCapFields[broker];
  if (!brokerMap) return '';
  const mapped = matchKey(brokerMap);
  if (mapped !== undefined) return mapped;
  return brokerMap['*'] ?? '';
}

/** 该券商的 volume cap 是否按整数取整。 */
export function isIntegerCapBroker(registry: BrokerParamFields, broker: string): boolean {
  return registry.integerCapBrokers.includes(broker);
}
