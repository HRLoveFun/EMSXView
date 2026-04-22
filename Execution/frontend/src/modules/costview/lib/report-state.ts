import { getHighestOrderSeverity } from './thresholds';
import type { CostViewConfig, CostViewFilterFormState, TcaReport } from '../types';

export function applyCostViewClientFilters(
  report: TcaReport,
  config: CostViewConfig,
  form: CostViewFilterFormState,
): TcaReport {
  if (!form.warningOnly) return report;

  const orders = report.orders.filter((order) => {
    const severity = getHighestOrderSeverity(order, config);
    return severity === 'warning' || severity === 'critical';
  });

  return {
    ...report,
    orders,
    total_orders: orders.length,
    offset: 0,
    filters: {
      ...report.filters,
      offset: 0,
    },
  };
}

export function paginateCostViewReport(
  report: TcaReport,
  limit: number,
  offset: number,
): TcaReport {
  const normalizedLimit = Math.max(1, limit);
  const totalOrders = report.total_orders;
  const lastPageOffset = totalOrders > 0
    ? Math.max(0, (Math.ceil(totalOrders / normalizedLimit) - 1) * normalizedLimit)
    : 0;
  const normalizedOffset = Math.min(Math.max(0, offset), lastPageOffset);

  return {
    ...report,
    orders: report.orders.slice(normalizedOffset, normalizedOffset + normalizedLimit),
    offset: normalizedOffset,
    limit: normalizedLimit,
    filters: {
      ...report.filters,
      offset: normalizedOffset,
      limit: normalizedLimit,
    },
  };
}

export function buildWarningOnlyPage(
  fullReport: TcaReport,
  config: CostViewConfig,
  form: CostViewFilterFormState,
  offset: number,
): TcaReport {
  const filteredReport = applyCostViewClientFilters(fullReport, config, form);
  return paginateCostViewReport(filteredReport, form.limit, offset);
}