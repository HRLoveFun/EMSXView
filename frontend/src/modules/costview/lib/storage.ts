import type {
  CostViewConfig,
  CostViewExportState,
  CostViewFilterFormState,
  CostViewModuleTab,
  CostViewViewState,
  MonitoringViewState,
  ScorecardFormState,
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

export const DEFAULT_VIEW_STATE: CostViewViewState = {
  activeTab: 'overview',
};

export const DEFAULT_EXPORT_STATE: CostViewExportState = {
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

export function loadCostViewConfig(): CostViewConfig {
  if (typeof window === 'undefined') return createDefaultCostViewConfig();

  const parsed = safeParse<CostViewConfig>(
    localStorage.getItem(COSTVIEW_CONFIG_KEY),
    createDefaultCostViewConfig(),
  );

  return {
    ...createDefaultCostViewConfig(),
    ...parsed,
    rules: {
      ...createDefaultCostViewConfig().rules,
      ...(parsed.rules ?? {}),
    },
    exportDefaults: {
      ...createDefaultCostViewConfig().exportDefaults,
      ...(parsed.exportDefaults ?? {}),
    },
    // 向后兼容：旧版本 localStorage 无该字段时回退为「全部市场」
    reportExchanges: Array.isArray(parsed.reportExchanges) ? parsed.reportExchanges : [],
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

export const DEFAULT_MONITORING_STATE: MonitoringViewState = {
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