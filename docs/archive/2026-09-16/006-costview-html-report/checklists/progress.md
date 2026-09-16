# 006-costview-html-report 实施进度跟踪

> 每完成一项，更新状态为 ✅；进行中 ⏳；阻塞 🔴

## 总览

| 项目 | 状态 |
|------|------|
| 方案落盘 (plan.md) | ✅ |
| 缺陷文档 `docs/report-tca-known-limitations.md` | ✅ |
| 渲染器迁移 `tca_report_html.py` → `CostView/src/monitoring/` | ✅ |
| 异常路由判定 `anomaly_query.py` | ✅ |
| 报告聚合扩展 `extra_kpis` / `impact_breakdown` / `anomaly` | ✅ |
| 后端端点 `GET /api/tca/monitoring/export-html` | ✅ |
| 前端 ReportView 导出按钮 + `fetchExportHtml` | ✅ |
| fill 历史注释语义修复（完成率 = fill/RouteShares） | ✅ |
| 后端+前端测试 | ✅ |
| 全量验证（pytest 258 / vitest 105 / lint / build） | ✅ |
| 提交 `5c9d9ba` | ✅ |
| 后端重启生效 + 404 故障修复 | ✅ |
| 第二批：分市场标签页 + 排行 SVG 自适应（CP-5） | ✅ |

## 检查点记录

### CP-5 第二批增强（2026-08-21）
- [x] 分市场标签页：后端 `markets` 清单（忽略 exchange 过滤）+ 前端 ReportView 标签页
- [x] 执行方排行 SVG 宽度自适应（`width=100%` + `preserveAspectRatio`）
- [x] 后端 `test_monitoring.py` 47 passed（+4 markets 用例）；CostView 全量 262 passed
- [x] 前端 costview 29 passed（+2 标签页用例）；tsc/lint 零错误
- [x] CLI 真实生成报告 5 张 SVG 全部 `width=100%`，无固定宽度残留

### CP-1 后端
- [x] `test_monitoring.py` 43 passed（含 export-html 200/422/空库降级、anomaly 判定）
- [x] CostView 全量 258 passed
- [x] backend 全量 207 passed（含 boundaries 12 passed）

### CP-2 前端
- [x] vitest 全量 105 passed（含导出按钮 2 用例）
- [x] tsc/lint 本次改动零错误（存量 execution/marketview 错误与本计划无关）

### CP-3 CLI 兼容
- [x] `generate_tca_report.py --last day` 真实生成 143KB HTML，含冲击/明细/口径

### CP-4 生产验证
- [x] `GET /api/tca/monitoring/export-html?last=day` → 200 + text/html + attachment
- [x] 后端重启（加载新代码）后前端导出正常

## 遗留

- 前端 `frontend/src/` 有大量未暂存改动（execution/databaseview/AppShell 等）——与本计划无关，
  是并行开发，本计划未触碰；下一会话注意区分。
- `tca_route_summary.fill` 历史注释问题已修复，但 `monitoring-metrics.ts:42` 的 `fill: '成交率'`
  label 仍不精确（fill 是股数，非成交率），可顺手改 `成交股数`。
