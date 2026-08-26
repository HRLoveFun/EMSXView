# 007-costview-report-filters 实施进度跟踪

> 每完成一项，更新状态为 ✅；进行中 ⏳；阻塞 🔴

## 总览

| 项目 | 状态 |
|------|------|
| 方案落盘 (plan.md) | ✅ |
| 调查（市场配置 / fx_rate 数据流） | ✅ |
| Config.MARKET_ORDER 市场配置 | ✅ |
| fx_fetcher 降级修复（最近已知汇率） | ✅ |
| processed_fills 加 fx_rate 列 + 迁移 | ✅ |
| S5.5 route 级 fx_rate 聚合 | ✅ |
| report_aggregator 总成交金额 | ✅ |
| 后端多值筛选 API | ✅ |
| 前端多选下拉 + 具体日期选项 | ✅ |
| 前端 KPI 总成交金额 | ✅ |
| HTML 分市场标签 + 总成交金额 | ✅ |
| 测试 + 全量验证 | ✅ |

## 检查点记录

### CP-1 调查（2026-08-21）
- [x] 无现成市场白名单配置文件；`BDIB_EXCHANGE`/`EXCHANGE_TIMEZONE` 均非报告市场配置
- [x] `tca_route_summary` 无 USD 价格；`fill_bdib.fx_rate` 大量 1.0 兜底（不可靠）
- [x] 决策：方案 B（processed_fills 加 fx_rate 列）+ 修 FX 降级 + Config.MARKET_ORDER

### CP-2 实施完成（2026-08-21）
- [x] `Config.MARKET_ORDER`：34 个市场（Exchange → 中文名，顺序即标签页顺序）
- [x] `fx_fetcher`：额度暂停/失败回退最近已知汇率（`_RECENT_RATES` 缓存），非 1.0 兜底
- [x] `processed_fills` 加 `fx_rate` 列（幂等 ALTER 迁移）；`tca_route_summary` 加 `fx_rate` 列
- [x] S5.5 `_enrich_fills_with_fx_rate`：从 fill_bdib 回填 processed_fills 并写回（方案 B）；
      `tca_route_metrics` 按 fill 量加权聚合 route 级 fx_rate
- [x] `report_aggregator`：KPI 增 `notional`/`notional_usd`/`fx_coverage`；
      `markets` 增每市场成交金额；新增 `filter_options`（brokers/algos/symbols distinct）；
      `_build_where` 支持逗号分隔多值 → IN 匹配
- [x] HTML 报告：KPI 增「总成交金额（美元）」卡片（含 fx 覆盖率副标题）；
      新增「分市场概览」radio 驱动 CSS 标签页（Config.MARKET_ORDER 顺序，每市场成交金额表）
- [x] 前端：`MultiSelectFilter` 组件（Popover+Checkbox 多选下拉，带选中 Badge）；
      ReportView 市场/Broker/Algo/Symbol 多选 + 时间范围「指定日期/范围」自定义区间；
      KPI 卡片增总成交金额（美元）；api.ts 支持数组参数 + 显式日期区间

### CP-3 全量验证
- [x] 后端：CostView 265 passed（+3）；DataPipeline 186 passed（+4）；backend 全量 207 passed；
      boundaries 12 passed；quota_pause 10 passed（+1 FX 降级）
- [x] 前端：costview 33 passed（+4）；全量 110 passed；tsc/lint 零错误；build 成功
- [x] 真实数据：US+JP 多值过滤 route 数 = 单值求和（305+40=345）✓；filter_options 返回正确
- [x] CLI：`generate_tca_report.py --last day` 生成含分市场标签页 + 美元成交金额卡片的 HTML

### CP-4 分市场标签页修复（2026-08-24）
- [x] HTML 分市场标签页从 CSS `:target` 锚点改为 **radio 驱动纯 CSS 标签页**（修复虚假跳转）：
      默认选中「全部」、切换无页面滚动跳转、零 JS 保持离线自包含
- [x] 字段文案统一为「总成交金额（美元）」/「成交金额（美元）」/「成交金额（本币）」
      （HTML KPI 卡片 + 市场汇总表列头；前端 ReportView KPI 卡片）
- [x] 测试：后端 `test_monitoring.py` 新增 `test_export_html_market_tabs_radio` /
      `test_export_html_usd_amount`（52 passed）；前端 monitoring-view 新增美元 KPI 用例（33 passed）

### CP-5 市场成交金额图表（2026-08-24）
- [x] 后端 `report_aggregator.py` 新增两个查询（均尊重 broker/algo/symbol/exchange 过滤）：
      `market_notional_ranking`（按市场成交金额排名，USD 降序，无 fx_rate 列时回退本币排序）
      与 `market_notional_trend`（date × Exchange 每日 USD 成交金额点列）
- [x] 前端 `ReportView.tsx` 新增两张图并置于 KPI 之后、原图表之前：
      「按市场的成交金额（美元）排名」（横向条形，USD 降序，中文市场名）
      与「按市场的成交金额（美元）每日趋势」（各市场多折线）
- [x] 测试：后端 `test_monitoring.py` 新增 ranking/trend/过滤 3 用例（55 passed）；
      前端 monitoring-view 新增图表渲染用例（34 passed）；tsc/lint 零错误

## 遗留

- `tca_route_summary.fx_rate` 需管道重跑（S5.5）才回填；当前真实库已加列但 fx_rate 为 NULL，
  USD 成交金额暂按 1.0 换算（fx_coverage=0）。
- 历史日期 USD 成交金额需跑 `reprocess` 或增量 S5.5 回填。
