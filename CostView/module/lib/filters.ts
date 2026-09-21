import type { CostViewFilterFormState, TcaFilterPayload } from '../types';

/** 分析筛选表单 → 请求 payload。
 *
 *  `ScorecardView` 与 `EvaluationView` 共用同一转换（避免两处转换漂移）。
 *  原定义在 `ScorecardView` 内并导出，会触发 `react-refresh/only-export-components`
 *  警告 —— 组件文件应只导出组件，故抽到本模块。
 */
export function analysisFiltersToPayload(form: CostViewFilterFormState): TcaFilterPayload {
  const payload: TcaFilterPayload = {};
  const orderIds = form.orderIds
    .split(/[\n,]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (orderIds.length) payload.order_ids = orderIds;
  if (form.algo) payload.algo = form.algo;
  if (form.startDate) payload.start_date = form.startDate.replace(/-/g, '');
  if (form.endDate) payload.end_date = form.endDate.replace(/-/g, '');
  if (form.broker) payload.broker = form.broker.trim();
  if (form.symbol) payload.symbol = form.symbol.trim();
  return payload;
}
