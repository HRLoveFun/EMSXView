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
});
