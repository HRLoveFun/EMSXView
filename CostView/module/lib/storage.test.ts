import { beforeEach, describe, expect, it } from 'vitest';
import { loadCostViewConfig } from './storage';

const CONFIG_KEY = 'emsx_costview_config_v1';

describe('CostView storage rule-key migration', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('migrates legacy tracking_error_bps into pnl_vwap_bps', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: {
        tracking_error_bps: {
          key: 'tracking_error_bps',
          label: 'Tracking Error',
          mode: 'absolute-above',
          warning: 7,
          critical: 9,
          enabled: true,
          decimals: 1,
          unit: 'bps',
          description: '',
        },
      },
    }));

    const config = loadCostViewConfig();

    expect(config.rules.pnl_vwap_bps.warning).toBe(7);
    expect(config.rules.pnl_vwap_bps.critical).toBe(9);
    expect(config.rules.pnl_vwap_bps.key).toBe('pnl_vwap_bps');
    expect('tracking_error_bps' in config.rules).toBe(false);
  });

  it('keeps the new key when both old and new exist', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: {
        tracking_error_bps: { key: 'tracking_error_bps', mode: 'absolute-above', warning: 7 },
        pnl_vwap_bps: { key: 'pnl_vwap_bps', mode: 'absolute-above', warning: 12 },
      },
    }));

    const config = loadCostViewConfig();

    expect(config.rules.pnl_vwap_bps.warning).toBe(12);
  });

  it('refreshes code-owned presentation metadata while keeping user thresholds', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: {
        fill_pct: {
          key: 'fill_pct', label: 'Fill %', mode: 'below', warning: 65,
          critical: 40, enabled: true, decimals: 1, unit: 'percent',
          description: 'stale',
        },
      },
    }));

    const config = loadCostViewConfig();

    // 用户可编辑字段以本地配置为准
    expect(config.rules.fill_pct.warning).toBe(65);
    expect(config.rules.fill_pct.critical).toBe(40);
    // 展示元数据以代码为准：旧标签不再残留在浏览器里（ADR-0018 §10.5）
    expect(config.rules.fill_pct.label).toBe('Fill Rate');
    expect(config.rules.fill_pct.description)
      .toBe('Lower fill rate indicates incomplete execution.');
  });

  it('fills missing fields from defaults for partial stored rules', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: { fill_pct: { key: 'fill_pct', mode: 'below', warning: 70 } },
    }));

    const config = loadCostViewConfig();

    expect(config.rules.fill_pct.warning).toBe(70);
    expect(config.rules.fill_pct.critical).toBe(50);
    expect(config.rules.fill_pct.unit).toBe('percent');
  });

  it('migrates stale default probe mode to above-strict for pre-v2 configs', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: {
        overfill_pct: {
          key: 'overfill_pct', label: 'Overfill', mode: 'above',
          warning: 100, critical: 110, enabled: true, decimals: 1, unit: 'percent',
          description: 'stale',
        },
      },
    }));

    const config = loadCostViewConfig();

    // 存储的 mode 是 v1 代码默认值（above）而非用户显式选择 → 迁移为当前默认
    expect(config.rules.overfill_pct.mode).toBe('above-strict');
    expect(config.rules.overfill_pct.warning).toBe(100);
    // 版本号写回，迁移只执行一次
    expect(config.ruleSchemaVersion).toBe(2);
  });

  it('keeps user-chosen modes that differ from the stale default', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      rules: {
        overfill_pct: {
          key: 'overfill_pct', label: 'Overfill', mode: 'below',
          warning: 100, critical: 110, enabled: true, decimals: 1, unit: 'percent',
          description: 'stale',
        },
      },
    }));

    const config = loadCostViewConfig();

    // mode 是用户显式选择（≠ 旧默认 above）→ 不迁移
    expect(config.rules.overfill_pct.mode).toBe('below');
  });

  it('does not re-migrate configs already stamped with the current schema version', () => {
    localStorage.setItem(CONFIG_KEY, JSON.stringify({
      ruleSchemaVersion: 2,
      rules: {
        overfill_pct: {
          key: 'overfill_pct', label: 'Overfill', mode: 'above',
          warning: 100, critical: 110, enabled: true, decimals: 1, unit: 'percent',
          description: 'user picked inclusive boundary',
        },
      },
    }));

    const config = loadCostViewConfig();

    // v2 配置里 mode: above 属用户显式选择（改回含边界语义）→ 不覆盖
    expect(config.rules.overfill_pct.mode).toBe('above');
  });
});
