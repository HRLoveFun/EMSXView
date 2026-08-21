# 实施计划: CostView 前端一键导出 HTML 报告（006）

**Branch**: `main` | **Date**: 2026-08-21 | **状态**: 已完成（提交 `5c9d9ba`）

**门控规范**: `docs/spec/plan-design-principles.md`（G0-G3）

---

## Summary

为 CostView 增加前端一键导出 HTML 报告能力：Report 页"导出 HTML 报告"按钮 →
后端 `GET /api/tca/monitoring/export-html` → 自包含静态 HTML 附件下载。
同时对齐学术框架（`docs/textbook/股票交易执行质量与交易成本分析（TCA）：跨时期学术研究综述与方法框架.md`
模块 B/D）补齐报告聚合层指标，并将报告口径缺陷落档。

## 已完成交付（提交 `5c9d9ba`，17 文件 +874/-28）

| # | 交付 | 文件 |
|---|------|------|
| 1 | 渲染器迁移 + 增强 | `tca_report_html.py` 迁入 `CostView/src/monitoring/`（CLI `generate_tca_report.py` 改 import 保持兼容）；S1 十卡 / S4 冲击表 / S6 明细表 / 口径脚注 |
| 2 | 异常路由判定模块 | `CostView/src/monitoring/anomaly_query.py`（阈值与前端 `DEFAULT_RULES` 对齐、可参数化、无上限明细） |
| 3 | 报告聚合扩展 | `CostView/src/monitoring/report_aggregator.py` 新增 `extra_kpis` / `impact_breakdown` / `anomaly` |
| 4 | 后端端点 | `CostView/api/routers/monitoring.py` 新增 `GET /api/tca/monitoring/export-html`（附件下载，文件名 `tca_report_<start>_<end>.html`） |
| 5 | 前端按钮 | `frontend/src/modules/costview/components/ReportView.tsx` + `services/api.ts`（`fetchExportHtml` Blob 下载，阈值随请求下发） |
| 6 | 缺陷文档 | `docs/report-tca-known-limitations.md`（K1-K4 硬缺口 + K5-K9 已补项） |

## 报告结构（定稿）

```
头部（标题/生成时间/过滤/口径脚注）
S1  KPI 卡片（10 张）：Route 总数·总股数·加权 pnl_vwap·par_rate·RPM
    + 加权 arrival 成本·加权 IS·风险 stddev/CVaR·平均完成率·异常路由数
S2  分布 + 按日走势（2 SVG）
S3  Broker / Algo 排行（2 SVG）
S4  市场冲击分解表（temp 5/10/30min + perm + close_cost）
S5  PWP 分档曲线（SVG）
S6  异常路由明细表（无上限，critical→warning 排序，19 列）
S7  指标覆盖率表（38 项）
S8  BDIB 缺口附录
页脚（口径脚注重复）
```

## 关键技术决策（下一会话须知）

1. **fill 口径**：`tca_route_summary.fill` 为**成交股数**（`tca_route_metrics.py:293` FillShares 总和），
   完成率 = `fill / RouteShares`。已同步修正前端 `thresholds.ts` 的 fill_pct 语义
   （`fill/route_shares*100`）及 `TcaOrderTable`/`AnalysisView` 展示。
2. **异常判定**：6 条阈值规则（tracking/fill/volADV/volInterval/intradayVol/priceMove），
   映射见 `anomaly_query.py::_METRIC_MAP`，与前端 `thresholds.ts::getMetricValue` 完全一致。
3. **阈值两处常量**：后端 `anomaly_query.py::DEFAULT_THRESHOLDS` 与前端
   `thresholds.ts::DEFAULT_RULES` 需同步维护；前端经 `fetchExportHtml` 显式传 `thresholds` 参数覆盖。
4. **渲染复用**：CLI（`generate_tca_report.py`）与 API 共用同一 `render_report_html()`，
   改动渲染器会同时影响两者（统一增强）。
5. **后端重启**：新增端点后需重启 `:3000`（或 `:8002`）进程才会生效（见故障排查记录）。

## 故障排查记录（2026-08-21）

- **症状**：前端点击"导出 HTML 报告"报 404 "Not Found"。
- **根因**：非代码 bug——`export-html` 已正确注册（backend 桥接 router
  `backend/api/routers/costview.py` 自动聚合 `CostView/api/routers/monitoring`），
  但运行中的 `:3000` uvicorn 进程是旧代码（09:24 启动，早于提交 `5c9d9ba`）。
- **修复**：停旧进程树（uvicorn + 父隐藏 powershell），用
  `scripts/deploy/start-backend.ps1` 重启；验证
  `GET /api/tca/monitoring/export-html?last=day` → 200 + `text/html` +
  `Content-Disposition: attachment; filename="tca_report_20260819_20260819.html"`。

## 验证结果

- 后端：`CostView/tests/test_monitoring.py` 43 passed；CostView 全量 258 passed；backend 全量 207 passed
- 前端：vitest 全量 105 passed（含导出按钮 2 用例）；tsc/lint 本次改动零错误
- CLI 兼容：`generate_tca_report.py --last day` 真实生成 143KB HTML 含全部新小节

## 后续优化方向

- **已增强（2026-08-21 第二批）**：分市场标签页（后端 `markets` 清单 + 前端 ReportView 标签页，忽略
  exchange 过滤）+ 执行方排行 SVG 宽度自适应（`width=100%` + `preserveAspectRatio`）。
  测试：后端 `test_monitoring.py` 47 passed（+4 markets 用例）、CostView 262 passed、
  前端 costview 29 passed（+2 标签页用例）、tsc/lint 零错误。
- **已知范围外**（`docs/report-tca-known-limitations.md`）：显性费用/返佣、L2 订单簿、事前预测、可操作性维度
- **可增强**：报告加导出时间戳文件名；明细表按需分页/排序控件；报告内嵌过滤条件回显；支持 order 级明细
