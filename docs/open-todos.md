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
| T4 | `tca_route_summary.fx_rate` 历史回填 | `specs/007-costview-report-filters/checklists/progress.md` 遗留 | ✅ | 2026-09-01 诊断验证全量 0% NULL（8/26 全量重算 + backfill_tca_route_fx 已覆盖） |
| T5 | 异常明细 arrival_cost_bps / opportunity_cost / wagner_is_bps / cost_cvar / order_duration_sec / recovery_truncated 真实库 100% NULL（Phase 0/1 核心指标列从未回填）；需重跑 S3 管道回填 | `specs/008-costview-anomaly-detail/plan.md` 调查结论 | ✅ | 2026-09-01 诊断验证：p_arrival/wagner_is 覆盖 87-95%（8/27-28 全量重算已回填），残余 ~3% 为 bdib_missing 真缺口 |
| T6 | 异常明细筛选规则 `fill_pct` 后端映射 bug 已修正：原用 `fill`(股数)比对阈值（永远不触发），现对齐前端用完成率百分比 | `specs/008-costview-anomaly-detail/plan.md` | ✅ | 后端 `anomaly_query._METRIC_MAP` fill_pct → completion_rate×100 |
| T7 | 异常明细完成率计算经核实正确（`fill/RouteShares`，0% NULL）；无需改动 | `specs/008-costview-anomaly-detail/plan.md` 调查结论 | ✅ | — |
| T8 | CostView 指标覆盖率修复：① 计划任务 CostView_DailyUpdate 被禁用致日更断流 8/27-8/31（已 re-enable + 回补）；② bar 时间戳区间语义对齐（纯竞价路由末 bar fallback，修复 par_rate/pnl_vwap/par_rate_close 大面积 NULL）；③ 覆盖率分母剔除白名单外交易所 + SLA 豁免口径 | `008-costview-report-enhancement` 分支 | ✅ | 2026-09-02 终验：全量 180 日重算完成，par_rate 全量 NULL 60%→20%，SLA 口径下 continuous 类 52→81%；调度恢复后日更已自动产出 9/1 数据 |
| T9 | 重算 20260901 的 temp_impact/perm_impact（next_day_close 结构性延迟：需等 9/3 日更产出 9/2 daily_summary 后执行 `recompute_all_tca_route_metrics.py --dates 20260901`） | `008-costview-report-enhancement` | ⏳ | 8/31 已于 9/2 补重算回填（temp5 20.6→60.0%、perm 0→54.2%）；9/1 同理待次日数据 |

## 已完成

（暂无）
