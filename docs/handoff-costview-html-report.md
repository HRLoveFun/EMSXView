# CostView HTML 报告 — 交接文档（下一会话）

> 用途：供"优化 HTML 报告"的下一会话快速接手。
> 关联：`specs/006-costview-html-report/plan.md`（本次实施记录）、
> `docs/report-tca-known-limitations.md`（口径缺陷清单）、提交 `5c9d9ba`。

## 现状一句话

CostView Report 页已有"导出 HTML 报告"按钮 → `GET /api/tca/monitoring/export-html`
→ 自包含静态 HTML（内联 CSS + SVG 图表，零 JS 依赖），内容 8 小节，与 CLI
`scripts/reports/generate_tca_report.py` 共用同一渲染器。

## 关键文件地图

| 文件 | 职责 |
|------|------|
| `CostView/api/routers/monitoring.py` | export-html 端点（`_parse_thresholds` / `_load_health_appendix`） |
| `CostView/src/monitoring/tca_report_html.py` | HTML 渲染器（纯标准库，改样式/结构在此） |
| `CostView/src/monitoring/report_aggregator.py` | 报告数据聚合（KPI/走势/排行/直方图/PWP/extra/impact/anomaly） |
| `CostView/src/monitoring/anomaly_query.py` | 异常路由判定 + 阈值默认值 `DEFAULT_THRESHOLDS` |
| `CostView/src/monitoring/__init__.py` | 包导出（新模块须在此注册） |
| `CostView/src/monitoring/metric_coverage.py` | 38 项指标覆盖率白名单 `COMPUTED_METRICS` |
| `CostView/src/monitoring/bdib_health.py` | BDIB 健康附录 |
| `CostView/src/monitoring/time_range.py` | last 预设/日期区间解析 |
| `frontend/src/modules/costview/components/ReportView.tsx` | 导出按钮 + 阈值下发 |
| `frontend/src/modules/costview/services/api.ts` | `fetchExportHtml` |
| `frontend/src/modules/costview/lib/thresholds.ts` | 前端阈值（与后端 `DEFAULT_THRESHOLDS` 双处同步） |
| `scripts/reports/generate_tca_report.py` | CLI 入口（与 API 共用渲染器） |
| `CostView/tests/test_monitoring.py` | 后端测试（43 用例） |
| `frontend/src/modules/costview/__tests__/monitoring-view.test.tsx` | 前端导出按钮测试 |

## 数据流

```
前端 ReportView（form: last+broker/algo/symbol/exchange + thresholds）
  → GET /api/tca/monitoring/export-html
  → monitoring.py: _resolve_range → ThresholdRules.from_payload
  → TcaReportAggregator.build_report(start,end, filters, metrics, thresholds)
      ├─ _query_kpi / _query_daily_series / _query_rankings / _query_pnl_histogram / _query_pwp_curve
      ├─ _query_extra_kpis（arrival/IS/stddev/cvar/p95/avg_fill）
      ├─ _query_impact_breakdown（temp 5/10/30 + perm + close_cost）
      ├─ MetricCoverageService（S7 覆盖率）
      └─ query_anomaly_routes（S6 明细，阈值判定）
  → BdibHealthService（S8 附录）
  → render_report_html(report, health, generated_at)
  → Response(text/html, Content-Disposition: attachment, tca_report_<start>_<end>.html)
  → 前端 Blob 下载
```

## 关键语义（改前必读）

### fill 是成交股数，不是百分比！
- `tca_route_summary.fill` = FillShares 总和（`tca_route_metrics.py:293`）
- 完成率 = `fill / RouteShares`（0-1），前端展示 ×100
- 前端 `thresholds.ts::getMetricValue('fill_pct')` 已修正为 `(fill/route_shares)*100`
- **勿再**把 `fill` 直接当百分比（历史 bug 已修）

### 阈值双处常量
- 后端：`anomaly_query.py::DEFAULT_THRESHOLDS`
- 前端：`thresholds.ts::DEFAULT_RULES`
- 前端导出时显式传 `thresholds` 参数覆盖（含 mode/warning/critical/enabled）
- 改阈值须同步两处

### 判定规则（S6 明细）
| 前端 key | 后端字段 | 缩放 |
|---|---|---|
| tracking_error_bps | pnl_vwap | ×1 |
| fill_pct | fill/route_shares | ×100 |
| volume_pct_adv20 | par_rate | ×100 |
| volume_pct_interval | par_rate_continuous | ×100 |
| intraday_volatility | pnl_vwap_continuous | ×0.01 |
| price_movement_pct | rpm | ×1 |

### 渲染器共用
- CLI 与 API 共用 `render_report_html()`——改渲染器影响两处（统一增强是特性）
- 渲染器零依赖（纯 Python 生成 HTML + SVG），无 JS

### 新增模块注意
- 新 py 模块须在 `CostView/src/monitoring/__init__.py` 注册导出
- 端点改后须**重启后端进程**才生效（`scripts/deploy/start-backend.ps1`；本次曾因旧进程 404）

## 当前已知问题 / 可优化点

1. **文件名**：`tca_report_<start>_<end>.html` 无时间戳，同区间重复下载会覆盖（浏览器默认）。可加 `_HHMMSS`。
2. **明细表**：S6 无分页/排序控件，大量异常时 HTML 大（当前 143KB）。可加前端分页或后端 LIMIT+分页。
3. **`monitoring-metrics.ts:42`**：`fill: '成交率'` label 不精确，应为 `成交股数`（监控热力图展示用，非完成率）。
4. **范围外**（`docs/report-tca-known-limitations.md`）：显性费用/返佣/税费（K1）、L2 订单簿（K2）、事前预测（K3）、可操作性（K4）——有条件后补齐。
5. **order 级明细**：当前 S6 是 route 级；如需 order 级可复用 `build_order_report()` 聚合逻辑。

## 已完成增强（2026-08-21 第二批）

### 分市场标签页
- 后端 `report_aggregator.py::_query_markets()`：报告新增 `markets` 清单（Exchange 去重 + route 数，
  **忽略 exchange 过滤**，尊重 broker/algo/symbol/preset），供前端标签页展示全部市场。
- 前端 `ReportView.tsx`：过滤栏去掉 exchange 输入框，改为**分市场标签页**（全部 + 各市场）。
  切换标签 → 按 Exchange 重载报告；导出 HTML 时自动携带当前市场。
- 测试：后端 `test_monitoring.py` 新增 markets 4 用例；前端 monitoring-view 新增标签页 2 用例。

### HTML 分市场标签页（radio 驱动，修复虚假跳转）
- `tca_report_html.py::_render_market_tabs`：从 CSS `:target` 锚点方案改为 **radio 驱动的纯 CSS 标签页**
  （`input:checked + label` 高亮 + `:checked ~ .mk-panel` 显示面板）。
- 修复 `:target` 的"虚假跳转"：早期方案点击标签产生页面锚点跳转（滚动跳动），且首次加载不显示任何面板；
  radio 方案默认选中「全部」、切换无滚动跳转，零 JS 保持离线自包含。
- 面板序号约定：panel 1 = 全部，市场 i → `nth-of-type(i+2)`。

### 执行方排行 SVG 宽度自适应
- `tca_report_html.py::_svg_hbar`：`width` 从固定 `780` 改为 `100%` + `preserveAspectRatio`
  （与分布与走势图 `_svg_wrap` 一致），排行图不再溢出面板。
- 验证：CLI 生成报告 5 张 SVG 全部 `width="100%"`，无固定宽度残留。

## 验证命令

```bash
# 后端
python -m pytest CostView/tests/test_monitoring.py -q
# 前端
cd frontend && npx vitest run src/modules/costview/
# CLI 真实生成
python scripts/reports/generate_tca_report.py --last day
# 端点直测
curl "http://localhost:3000/api/tca/monitoring/export-html?last=day" -o report.html
# 边界
python -m pytest backend/api/tests/boundaries/ -q
```
