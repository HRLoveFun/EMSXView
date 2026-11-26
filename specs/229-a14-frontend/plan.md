# 229 — A14 第三批：前端三件套拆分

> 来源：`audit-remediation-2026-10-25.md` **A14（E5）**「前端三件套（RouteTable 858 行等）排技术债」
> 分支：`229-a14-frontend`（worktree `../EMSXView-wt-229-a14-frontend`，基于 `origin/main`）

## 问题

三个前端文件长期超长，单文件承载状态、纯逻辑、表格/图表与子组件，难以测试与复用：

| 文件 | 拆分前 |
|---|---:|
| `ExecutionView/module/views/RouteTable.tsx` | 857 行 |
| `MarketView/module/components/monitor-board-panel.tsx` | 754 行 |
| `CostView/module/components/ReportView.tsx` | 727 行 |

## 方案（纯搬移，行为不变）

- **MonitorBoardPanel**：抽出
  - `monitor-board/filters.ts`：`marketOf` / 筛选类型与纯函数；
  - `monitor-board/parts.tsx`：`SeverityCell` / `HighlightModule` / `FilterPanel` / `Row` / `FilterableHeader`。
- **ReportView**：
  - `report-view/kpi-cards.tsx`：`KpiCards` + FX 覆盖率副标题；
  - `report-view/charts.tsx`：`ChartPanel` 与全部图表（KPI 分布、市场趋势、排行、PWP 等）。
- **RouteTable**：
  - `route-table/helpers.ts`：排序/筛选/分组纯函数与常量；
  - `route-table/status-badge.tsx`：状态徽章；
  - `route-table/route-row.tsx`：行渲染；
  - `route-table/group-header.tsx`：二级分组表头。
- 顶层组件只保留状态编排、工具栏、表格骨架与对话框。

## 验收

- `tsc -b frontend` 通过（含 `noUnusedLocals`）。
- 行数：RouteTable 857→640、monitor-board 754→423、ReportView 727→394（合计 −36%）。
- 既有 `monitor-board-panel.test.tsx` 由 CI vitest 覆盖；无行为/文案/字段改动。
- `doc_check.py` 退出码 0。

## 边界

本轮只做文件/组件拆分，不改后端契约、筛选逻辑、图表配置或任何用户可见文案；A14 至此收口。
