# 实施计划: CostView 报告筛选增强 + 总成交金额（007）

**Branch**: `main` | **Date**: 2026-08-21 | **状态**: 已完成（本轮实施）

**门控规范**: `docs/spec/plan-design-principles.md`（G0-G3）

---

## Summary

增强 CostView 报告（Report 页 + HTML 导出）的筛选能力与总成交金额指标：

1. **前端多选筛选**：市场/Broker/Algo/Symbol 从单值文本框改为多选下拉（可多选）。
2. **时间范围**：增加"具体日期/范围"选项（除 last 预设外，支持 start/end 显式区间）。
3. **总成交金额（USD）**：KPI 卡片与 HTML 报告新增总成交金额。
4. **HTML 报告分市场标签页**：市场由配置文件（`DataPipeline/config.py::Config.MARKET_ORDER`）设定。

## 前置调查结论

- **无现成"市场白名单"配置文件**：最近似的是 `Config.BDIB_EXCHANGE`（管 BDIB 拉取）与
  `EXCHANGE_TIMEZONE`（时区映射），均非报告市场配置 → 新增 `Config.MARKET_ORDER`。
- **无可靠 USD 成交额**：`tca_route_summary`/`processed_fills` 只有本币价格；`fill_bdib` 有
  `fx_rate` 但大量为 1.0 兜底（额度暂停/拉取失败时）。方案：修 FX 降级逻辑 + 可靠持久化。

## fx_rate 数据流改造（方案 B）

- **存储**：`processed_fills` 新增 `fx_rate` 列（fill 级，从 `fill_bdib` 集成时带出/回填）。
- **S5.5 聚合**：`tca_route_metrics.py` 把 fill 级 `fx_rate` 按 fill 量加权聚合为 route 级
  `fx_rate`，写入 `tca_route_summary` 新列。
- **降级修复**：`fx_fetcher.py` 额度暂停/拉取失败时改为最近已知汇率（不回退 1.0）。

## 交付清单

| # | 交付 | 文件 |
|---|------|------|
| 1 | 市场配置 | `DataPipeline/config.py::Config.MARKET_ORDER`（有序 Exchange + 中文名） |
| 2 | FX 降级修复 | `DataPipeline/acquisition/fx_fetcher.py` |
| 3 | processed_fills 加列 | `columns.py` `PROCESSED_COLUMNS` + `inline_ddl.py` 迁移 |
| 4 | S5.5 route 级 fx_rate | `tca_route_metrics.py` + `stages_process.py::_enrich_fills_with_fx_rate` |
| 5 | 总成交金额聚合 | `report_aggregator.py` KPI/markets/filter_options |
| 6 | 后端多值筛选 | `report_aggregator._build_where`（逗号分隔 → IN） |
| 7 | 前端多选 + 日期 | `ReportView.tsx` + `MultiSelectFilter.tsx` + `api.ts` + `types.ts` |
| 8 | 前端 KPI 总金额 | `ReportView.tsx` KpiCards |
| 9 | HTML 分市场 + 总金额 | `tca_report_html.py` |
| 10 | 测试 | `test_monitoring.py` / 前端 vitest / `test_quota_pause.py` |

## 验证结果（2026-08-21）

- 后端：CostView 265 passed（+3）；DataPipeline 186 passed（+4）；backend 全量 207 passed；
  boundaries 12 passed；quota_pause 10 passed（+1 FX 降级）
- 前端：costview 32 passed（+3）；全量 110 passed；tsc/lint 零错误；build 成功
- 真实数据：US+JP 多值过滤 route 数 = 单值求和 ✓；CLI 生成含分市场标签 + USD 金额卡片

## 遗留

- `tca_route_summary.fx_rate` 需管道重跑（S5.5）才回填；当前真实库 fx_rate 为 NULL，
  USD 成交金额暂按 1.0 换算（fx_coverage=0）。历史日期需增量 S5.5 或 reprocess 回填。

