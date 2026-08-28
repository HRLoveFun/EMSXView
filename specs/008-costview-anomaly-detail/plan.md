# 008-costview-anomaly-detail — 异常路由明细重构

> 分支 `008-costview-report-enhancement`。目标：重构异常路由明细（S6 HTML 报告 + 前端 alert 表）的字段列与筛选规则。
>
> 关联：006-costview-html-report / 007-costview-report-filters；阈值逻辑对齐 `frontend/src/modules/costview/lib/thresholds.ts`。

## 调查结论（基线数据：真实库 tca_route_summary 151,886 行）

- **完成率**：`RouteShares`/`fill` 均 0% NULL，`fill/RouteShares` 计算正确，无缺失。无需改动公式。
- **arrival_cost_bps / opportunity_cost / wagner_is_bps / cost_cvar / order_duration_sec / recovery_truncated：100% NULL**。
  根因 = Phase 0/1 核心指标列（003-tca-core-benchmarks）从未回填进真实库（特性已合并 main，但生产表未重跑 S3）。
  属**数据回填**任务（见 T5 / open-todos T5），非代码缺陷；明细表已对 NULL 优雅显示 `—`。
- **fx_rate**：1.3% NULL → USD 成交金额基本可用，缺失行显示 `—`。
- **指标映射 BUG（修正项）**：后端 `anomaly_query._METRIC_MAP["fill_pct"]` 用原始 `fill`（股数）比对阈值（80/50），
  永远不触发；前端 `getMetricValue` 已正确用完成率百分比。需后端对齐。

## 任务

| # | 内容 | 状态 |
|---|------|------|
| T1 | 后端 anomaly_query：AnomalyRoute 加 currency/notional_local/notional_usd；fill_pct 映射修正为完成率% | ✅ |
| T2 | HTML S6 异常明细表加「成交金额（本币）/（美元）」两列 | ✅ |
| T3 | 后端 monitoring 新增 GET /api/tca/monitoring/anomaly-thresholds（阈值唯一真相源） | ✅ |
| T4 | 前端：拉取后端默认值 seed/Reset；类型加 fx_rate；TcaOrderTable 加成交金额列 | ✅ |
| T5 | 记录调查结论：Phase0/1 列 100% NULL → 数据回填 TODO；完成率核实正确 | ✅ |
| T6 | 测试 + lint/typecheck | ✅ |

## 设计要点

- **统一阈值真相源**：后端 `anomaly_query.DEFAULT_THRESHOLDS` 为权威默认；新增 API 暴露；
  前端保留本地副本作离线兜底，「Reset Defaults」与首装 seed 优先取后端。
- **成交金额**：本币 = `Amount`（列已存在）；美元 = `Amount * fx_rate`（fx_rate 缺失则不换算，显示 `—`）。
- **筛选规则可配置**：Configure 已支持 6 条规则（mode/warning/critical/enabled）；后端 `ThresholdRules.from_payload`
  已接受前端覆盖，无需改动。
