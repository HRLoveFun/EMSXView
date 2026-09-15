import type {
  CostViewConfig,
  CostViewExportState,
  CostViewFilterFormState,
  CostViewMetricKey,
  CostViewModuleTab,
  CostViewViewState,
  MonitoringViewState,
  ScorecardFormState,
  ThresholdRule,
} from '../types';
import { ALL_TCA_METRICS } from './monitoring-metrics';
import { createDefaultCostViewConfig } from './thresholds';

const COSTVIEW_CONFIG_KEY = 'emsx_costview_config_v1';
const COSTVIEW_FILTERS_KEY = 'emsx_costview_filters_v1';
const COSTVIEW_VIEW_KEY = 'emsx_costview_view_v1';
const COSTVIEW_EXPORT_KEY = 'emsx_costview_export_v1';
const COSTVIEW_SCORECARD_KEY = 'emsx_costview_scorecard_v1';
const COSTVIEW_MONITORING_KEY = 'emsx_costview_monitoring_v1';

export const DEFAULT_FILTER_FORM_STATE: CostViewFilterFormState = {
  orderIds: '',
  algo: '',
  startDate: '',
  endDate: '',
  broker: '',
  symbol: '',
  warningOnly: false,
  limit: 50,
};

const DEFAULT_VIEW_STATE: CostViewViewState = {
  activeTab: 'overview',
};

const DEFAULT_EXPORT_STATE: CostViewExportState = {
  lastExportAt: null,
  lastExportFormat: null,
  lastExportScope: null,
};

function safeParse<T>(value: string | null, fallback: T): T {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

/** 014: 规则键重命名迁移（tracking_error_bps → pnl_vwap_bps）。
 *  旧 localStorage 配置读取时映射，避免用户自定义阈值被静默丢弃。 */
function migrateRuleKeys(
  rules: Partial<Record<string, ThresholdRule>>,
): Partial<Record<CostViewMetricKey, ThresholdRule>> {
  const migrated: Record<string, ThresholdRule | undefined> = { ...rules };
  const legacy = migrated.tracking_error_bps;
  if (legacy && !migrated.pnl_vwap_bps) {
    migrated.pnl_vwap_bps = { ...legacy, key: 'pnl_vwap_bps' };
  }
  delete migrated.tracking_error_bps;
  return migrated as Partial<Record<CostViewMetricKey, ThresholdRule>>;
}


/** 展示元数据（label / description / decimals / unit）由代码持有：读取本地配置时以当前
 *  默认值刷新，避免历史配置把「Fill %」这类旧标签长期钉在浏览器里（后端已改而网页仍显示
 *  旧标签）；用户可编辑字段（mode / warning / critical / enabled）仍以本地为准。
 *  缺失字段回落到默认值，顺带兜住「旧版本只存了部分字段」的规则对象。
 *  约定见 ADR-0018 §10.5。 */
function refreshRulePresentation(
  rules: Partial<Record<CostViewMetricKey, ThresholdRule>>,
): Partial<Record<CostViewMetricKey, ThresholdRule>> {
  const defaults = createDefaultCostViewConfig().rules;
  const refreshed: Partial<Record<CostViewMetricKey, ThresholdRule>> = {};
  for (const [key, rule] of Object.entries(rules) as Array<[CostViewMetricKey, ThresholdRule]>) {
    const base = defaults[key];
    if (!base) {
      refreshed[key] = rule;
      continue;
    }
    refreshed[key] = {
      ...base,
      mode: rule.mode ?? base.mode,
      warning: rule.warning ?? base.warning,
      critical: rule.critical ?? base.critical,
      enabled: rule.enabled ?? base.enabled,
    };
  }
  return refreshed;
}

/** 阈值规则 schema 版本：v2 = 数据质量探针边界收紧（overfill_pct 改 above-strict，
 *  ADR-0018 §10.4/§10.5）。老配置（无版本号或 < 2）里保存的旧默认 mode 会随
 *  `thresholds` payload 每次查询下发、覆盖后端新默认 —— 读取时做一次性迁移。 */
const RULE_SCHEMA_VERSION = 2;

/** 各版本历史遗留的「旧代码默认 mode」：仅当存储值仍等于它时才迁移（用户显式改过的不动）。 */
const STALE_RULE_MODES: Partial<Record<CostViewMetricKey, ThresholdRule['mode']>> = {
  // v1 默认 above（含边界）；v2 起为 above-strict（严格大于，与 overfill 布尔标记同界）
  overfill_pct: 'above',
};

/** v1 → v2：把仍是旧默认值的探针 mode 迁移为当前代码默认，消除「后端已修、网页仍误报」。 */
function migrateStaleRuleModes(
  rules: Partial<Record<CostViewMetricKey, ThresholdRule>>,
): Partial<Record<CostViewMetricKey, ThresholdRule>> {
  const defaults = createDefaultCostViewConfig().rules;
  const migrated: Partial<Record<CostViewMetricKey, ThresholdRule>> = { ...rules };
  for (const [key, staleMode] of Object.entries(STALE_RULE_MODES) as Array<
    [CostViewMetricKey, ThresholdRule['mode']]
  >) {
    const rule = migrated[key];
    const base = defaults[key];
    if (rule && base && rule.mode === staleMode && base.mode !== staleMode) {
      migrated[key] = { ...rule, mode: base.mode };
    }
  }
  return migrated;
}

export function loadCostViewConfig(): CostViewConfig {
  if (typeof window === 'undefined') return createDefaultCostViewConfig();

  const parsed = safeParse<CostViewConfig>(
    localStorage.getItem(COSTVIEW_CONFIG_KEY),
    createDefaultCostViewConfig(),
  );
  // 无版本号的历史配置按 v1 处理（触发一次性模式迁移）
  const storedVersion = parsed.ruleSchemaVersion ?? 1;
  const rules = refreshRulePresentation(migrateRuleKeys(parsed.rules ?? {}));

  return {
    ...createDefaultCostViewConfig(),
    ...parsed,
    rules: storedVersion < RULE_SCHEMA_VERSION ? migrateStaleRuleModes(rules) : rules,
    exportDefaults: {
      ...createDefaultCostViewConfig().exportDefaults,
      ...(parsed.exportDefaults ?? {}),
    },
    // 向后兼容：旧版本 localStorage 无该字段时回退为「全部市场」
    reportExchanges: Array.isArray(parsed.reportExchanges) ? parsed.reportExchanges : [],
    ruleSchemaVersion: RULE_SCHEMA_VERSION,
  };
}

export function saveCostViewConfig(config: CostViewConfig): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_CONFIG_KEY, JSON.stringify(config));
}

/** 是否存在已保存的 CostView 配置（用于判断是否首装，以便从后端拉取默认阈值） */
export function hasSavedCostViewConfig(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(COSTVIEW_CONFIG_KEY) != null;
}

export function loadCostViewFilters(): CostViewFilterFormState {
  if (typeof window === 'undefined') return DEFAULT_FILTER_FORM_STATE;
  return {
    ...DEFAULT_FILTER_FORM_STATE,
    ...safeParse<Partial<CostViewFilterFormState>>(
      localStorage.getItem(COSTVIEW_FILTERS_KEY),
      DEFAULT_FILTER_FORM_STATE,
    ),
  };
}

export function saveCostViewFilters(filters: CostViewFilterFormState): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_FILTERS_KEY, JSON.stringify(filters));
}

export function loadCostViewViewState(): CostViewViewState {
  if (typeof window === 'undefined') return DEFAULT_VIEW_STATE;
  return {
    ...DEFAULT_VIEW_STATE,
    ...safeParse<Partial<CostViewViewState>>(
      localStorage.getItem(COSTVIEW_VIEW_KEY),
      DEFAULT_VIEW_STATE,
    ),
  };
}

export function saveCostViewActiveTab(activeTab: CostViewModuleTab): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_VIEW_KEY, JSON.stringify({ activeTab }));
}

export function loadCostViewExportState(): CostViewExportState {
  if (typeof window === 'undefined') return DEFAULT_EXPORT_STATE;
  return {
    ...DEFAULT_EXPORT_STATE,
    ...safeParse<Partial<CostViewExportState>>(
      localStorage.getItem(COSTVIEW_EXPORT_KEY),
      DEFAULT_EXPORT_STATE,
    ),
  };
}

export function saveCostViewExportState(state: CostViewExportState): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_EXPORT_KEY, JSON.stringify(state));
}

export const DEFAULT_SCORECARD_FORM_STATE: ScorecardFormState = {
  cohort: 'broker_strategy',
  minSampleSize: 10,
  maxOrders: 2000,
};

export function loadCostViewScorecardForm(): ScorecardFormState {
  if (typeof window === 'undefined') return DEFAULT_SCORECARD_FORM_STATE;
  return {
    ...DEFAULT_SCORECARD_FORM_STATE,
    ...safeParse<Partial<ScorecardFormState>>(
      localStorage.getItem(COSTVIEW_SCORECARD_KEY),
      DEFAULT_SCORECARD_FORM_STATE,
    ),
  };
}

export function saveCostViewScorecardForm(state: ScorecardFormState): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_SCORECARD_KEY, JSON.stringify(state));
}

// ── 监控页状态（时间范围预设 + 指标勾选）────────────────────────────────────

const DEFAULT_MONITORING_STATE: MonitoringViewState = {
  lastPreset: 'month',
  selectedMetrics: [...ALL_TCA_METRICS],
};

export function loadCostViewMonitoringState(): MonitoringViewState {
  if (typeof window === 'undefined') return DEFAULT_MONITORING_STATE;
  const parsed = safeParse<Partial<MonitoringViewState>>(
    localStorage.getItem(COSTVIEW_MONITORING_KEY),
    DEFAULT_MONITORING_STATE,
  );
  // 指标勾选需过滤掉白名单外的历史脏数据
  const validMetrics = (parsed.selectedMetrics ?? DEFAULT_MONITORING_STATE.selectedMetrics)
    .filter((m) => (ALL_TCA_METRICS as readonly string[]).includes(m));
  return {
    lastPreset: parsed.lastPreset ?? DEFAULT_MONITORING_STATE.lastPreset,
    selectedMetrics: validMetrics.length ? validMetrics : [...ALL_TCA_METRICS],
  };
}

export function saveCostViewMonitoringState(state: MonitoringViewState): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_MONITORING_KEY, JSON.stringify(state));
}
