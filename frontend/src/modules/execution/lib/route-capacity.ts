/**
 * 父单「可路由额度」计算的共享口径。
 *
 * 权威定义见后端 `backend/api/services/batch_route_service.py`
 * (`_validate_split_totals`)：
 *
 *   effective = max(0, order.remainingQuantity − Σ pending route.working)
 *
 * 前端必须在所有展示/校验处复用同一口径，否则会出现「前端放行、后端 BLOCK」
 * 或「额度被低估」两类偏差。lib 与 components 两侧共用本文件的常量与工具函数，
 * 避免各自维护一份导致漂移。
 */

import type { Order } from '@execution/types';

/**
 * 仍占用父单容量的路由状态集合。
 *
 * 这些状态下的路由量仍挂在 broker 未回，必须从父单可路由额度中扣除；
 * 终态路由（FILLED / CANCEL / DONE / REJECTED…）的成交量已体现在父单
 * `remainingQuantity` 上，不得重复扣减。
 *
 * 与后端 `pending_route_statuses` 逐项一致，改动需同步后端。
 */
export const PENDING_ROUTE_STATUSES: ReadonlySet<string> = new Set([
  'SENT', 'WORKING', 'PARTFILLED', 'QUEUED', 'HOLD',
  'CXLREQ', 'CXLREJ', 'CXLREP', 'CXLRPRQ', 'CXLRPRJ',
  'REPPEN', 'A-SENT', 'OA-SENT',
]);

/**
 * 父单可路由基数 = 剩余量（remainingQuantity），**不是**总量（quantity）。
 *
 * 已成交部分不能再路由出去；若误用 quantity，部分成交的订单会虚高
 * `filledQuantity` 的额度。`remainingQuantity` 缺失时回退
 * `quantity − filledQuantity`，并兜底不为负。
 */
export function remainingOf(o: Order): number {
  if (Number.isFinite(o.remainingQuantity) && o.remainingQuantity >= 0) {
    return o.remainingQuantity;
  }
  return Math.max(0, (o.quantity ?? 0) - (o.filledQuantity ?? 0));
}
