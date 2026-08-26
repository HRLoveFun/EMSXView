# 全局待办清单（Open TODOs）

> 聚合各计划文件（`specs/*/checklists/progress.md`）末尾的"遗留"小节与未收尾事项，
> 作为跨计划的单一待办入口，避免遗留项散落丢失。
>
> 状态标记：⏳ 待办 / ✅ 已完成 / 🔴 阻塞
> 维护约定：每完成一项更新状态并记录完成日期；来源计划关闭时，对应行可移除。

## 待办

| # | 事项 | 来源 | 状态 | 备注 |
|---|------|------|------|------|
| T1 | PR 合并回 main（004-backend-test-stabilization） | `specs/004-backend-test-stabilization/checklists/progress.md` | ⏳ | 功能已完成（26 项全修，本地 195 passed），待合并 |
| T2 | PR 合并回 main（005-bloomberg-quota-pause） | `specs/005-bloomberg-quota-pause/checklists/progress.md` | ⏳ | 功能已完成（全量回归通过），待合并 |
| T3 | `frontend/src/modules/costview/lib/monitoring-metrics.ts:42` fill label 文案 `'成交率'` 改为 `'成交股数'` | `specs/006-costview-html-report/checklists/progress.md` 遗留 | ⏳ | fill 是股数，非成交率 |
| T4 | `tca_route_summary.fx_rate` 需管道重跑（S5.5）才回填；当前真实库该列为 NULL，USD 成交金额暂按 1.0 换算（fx_coverage=0） | `specs/007-costview-report-filters/checklists/progress.md` 遗留 | ⏳ | 历史日期 USD 成交金额需跑 `reprocess` 或增量 S5.5 回填 |

## 已完成

（暂无）
