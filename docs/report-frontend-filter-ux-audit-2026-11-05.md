# 前端筛选交互盘点与改造优先级

> L3 | 权威：2026-11-05 前端「选项选择控件」盘点与已完成改造记录 | 不权威：各模块当前实现细节（以代码为准）
> 范围：`CostView/module`、`ExecutionView/module`、`MarketView/module`、`frontend/src`
> Last updated: 2026-11-05

---

## 1. 设计原则

目标是把「展开下拉 → 滚动 → 点选」压缩成「一次点击」或「输入即选」：

- **短枚举（2–6 项）平铺**：`SegmentedField`，点击即切换，多选可再点取消。
- **长列表可搜索**：`SearchableSelect`，输入即过滤（多关键词 AND）、↑↓/Enter/Esc、已选/最近/全部分组、已选 chip 可移除。
- **已选条件常驻**：`FilterSummaryBar`，每条可单独移除，附「清空全部」。
- **整组筛选可复用**：`SavedViewBar` + `lib/saved-views.ts`，命名保存、一键套用、按 scope 持久化。
- **常用维度在前，长尾折叠**：Trader 页把策略/算法/Broker/完成率/质量/排序收进「更多筛选」，并显示生效项数徽标。

---

## 2. 已完成（2026-11-05）

### 2.1 CostView（全模块）

| 区域 | 改造 |
| --- | --- |
| 交易员复盘台 `TraderFilterBar.tsx` | 5 处 `MultiSelectFilter` → `SearchableSelect`；完成率/质量/排序/方向 → `SegmentedField`；长尾条件折叠；已选 chip；命名视图；页码换算收敛到 `lib/trader-filters.ts` |
| Analysis `TcaFilterWorkbench.tsx` | Algorithm / Max Orders 原生 select → `SegmentedField` |
| Report `ReportView.tsx` | 市场/Broker/Algo/Symbol → `SearchableSelect`；时间范围/聚合粒度 → `SegmentedField` |
| Monitoring `MonitoringView.tsx` | 监控范围/聚合粒度 → `SegmentedField`；38 项指标面板增加搜索、「仅看已选」、「全选当前」 |
| Configure `ConfigureView.tsx` | 交易所 → `SearchableSelect`；导出格式/范围 → `SegmentedField` |
| Evaluation / ExportDialog / RegimeDistributionPanel | 趋势粒度 / 导出格式与范围 / regime 维度 → `SegmentedField` |
| 清理 | 删除被取代的 `MultiSelectFilter.tsx`、`SymbolSearchInput.tsx` |

新增基础设施：`SearchableSelect`、`SegmentedField`、`FilterSummaryBar`、`SavedViewBar`、
`lib/recent-values.ts`、`lib/saved-views.ts`、`lib/trader-filters.ts`；
测试见 `CostView/module/__tests__/filter-controls.test.tsx` 与 `trader-view.test.tsx`。

### 2.2 ExecutionView（两处最高频）

| 区域 | 改造 |
| --- | --- |
| `RouteTable.tsx` Status / Broker / Trader | `MultiSelectFilterPopover` 增加搜索、↑↓/Enter、已选置顶、计数徽标、「全选当前」 |
| `OrderTable.tsx` Status / Type / Trader | 删除各自内联弹层，统一复用上述组件；保留 All 行；`showAll` / `displayNames` 可配置 |

`TextFilterPopover` 维持现状（本身已是输入即过滤）。

---

## 3. 盘点结论（按痛点）

### A. 选项 > 10 且逐项点击

- ✅ `ExecutionView/module/views/RouteTable.tsx`：Status 22 项、Broker 17–22、Trader 动态 >10 —— 本次已改为可搜索。
- ✅ `ExecutionView/module/views/OrderTable.tsx`：Status 11、Trader 动态 —— 本次已改为可搜索。
- ⬜ `MarketView/module/components/monitor-board-panel.tsx`（列筛选面板，Risk notes 可 >10）—— 仍是 chip 平铺，无搜索/键盘。
- ⬜ 动态长列表下拉：`route-plan-manager.tsx`（Match Market、Broker datalist）、`unified-modify-route-dialog.tsx`（Strategy）、`broker-strategy-params-editor.tsx`（Strategy）。

### B. 短枚举仍走下拉

- `BatchOperationPanel.tsx`：字段（4）、TIF（4）；Status 下拉只有 `CANCELLED` 一项，语义上应改为确认按钮。
- `order-modify-dialog.tsx` / `unified-modify-route-dialog.tsx`：Order Type、TIF 各 4 项。
- `algo-launch-dialog.tsx`：Schedule Type（3）、Urgency（4）。
- `route-plan-manager.tsx`：Side / Split / Activation / Schedule（3/3/2/3）。
- Settings：`ParameterFrequencySection.tsx`（5 × 6 行）、`GlobalSection.tsx`（4）、`MonitorConditionsSection.tsx`（Yes/No）、`IntervalSeriesPanel.tsx`（4 个 bucket）。

### C. 一次性大量勾选

- `market-broker-mapping-section.tsx`：市场 × 券商权限矩阵（可达数百格），无全选/反选/搜索。
- `daily-broker-policy-confirm-modal.tsx`：每市场 10–20 个券商 chip，逐项确认。
- `broker-selection-panel.tsx` 已有全选，相对最好。

### D. 筛选状态易丢失

OrderTable / RouteTable 的筛选全部为组件内 `useState`，切页签或刷新即丢；全仓库没有 URL 参数同步，也没有通用 `useLocalStorage`。
CostView 的 `lib/saved-views.ts` / `lib/recent-values.ts` 可直接作为模板。

---

## 4. 后续优先级（收益 / 成本）

1. **OrderTable / RouteTable 的筛选记忆**：复用命名视图与最近值，解决「切页签即丢」。
2. **MarketView MonitorBoard 列筛选**：改成可搜索多选；需同步重写 6–8 条测试断言。
3. **修改/下单类对话框的短枚举**：Type / TIF / Schedule / Urgency / Side / Split → `SegmentedField`，无测试锁定，改动机械。
4. **BatchOperationPanel**：字段/TIF 分段控件；删除单项 Status 下拉。
5. **Settings 页重复下拉**：频率（5 × 6 行）、Reconcile、Yes/No、Bucket。
6. **低频大批量勾选**：权限矩阵与每日券商确认补「全选/反选/搜索」。

不建议投入：`MarketView/module/components/filter-bar.tsx`、`pool-board-panel.tsx`、`pre-trade-board-panel.tsx`、`export-orders-panel.tsx`、`snapshot-table.tsx`、`intraday-feature-panel.tsx` 目前**未被 `MarketViewModule` 挂载**，全仓库只有测试引用。先确认产品是否保留，删除比改造更划算。

---

## 5. 复用注意

- CostView 的新组件是模块内实现，未放到 `frontend/src/components`；ExecutionView 目前维护自己的 `MultiSelectFilterPopover`，避免跨模块深引用。
- 多关键词匹配（含展示名命中）已抽到 `frontend/src/shared/lib/search-match.ts`，CostView 与 ExecutionView 共用；后续抽组件时连同存储前缀一起参数化。
- 若后续三个模块都要用，建议把 `SearchableSelect` / `SegmentedField` 抽到 `frontend/src/components/filters/`，再让各模块引用共享实现；同时把存储前缀从 `emsx_costview_*` 参数化。
- 改造 `MarketView` 前先读 `MarketView/module/components/monitor-board-panel.test.tsx`：该文件的按钮名、`aria-haspopup="dialog"`、`Filter · Exchange` 标题等断言会随控件形态变化而失效。

---

## 6. 验证

```bash
npm run typecheck
npm run lint
npm run lint:modules
npm test
npm run build:costview
npm run build:execution
```

本次交付：前端全量 358 个测试通过，typecheck / lint / lint:modules / 两个模块构建均通过。
