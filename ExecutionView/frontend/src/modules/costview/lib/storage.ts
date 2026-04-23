import type {
  CostViewConfig,
  CostViewExportState,
  CostViewFilterFormState,
  CostViewModuleTab,
  CostViewViewState,
} from '../types';
import { createDefaultCostViewConfig } from './thresholds';

const COSTVIEW_CONFIG_KEY = 'emsx_costview_config_v1';
const COSTVIEW_FILTERS_KEY = 'emsx_costview_filters_v1';
const COSTVIEW_VIEW_KEY = 'emsx_costview_view_v1';
const COSTVIEW_EXPORT_KEY = 'emsx_costview_export_v1';

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
  };
}

export function saveCostViewConfig(config: CostViewConfig): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(COSTVIEW_CONFIG_KEY, JSON.stringify(config));
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