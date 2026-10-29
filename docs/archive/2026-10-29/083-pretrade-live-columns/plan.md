# 083 — 盘前单表格重排：静态/日度/实时列分界 + 覆盖率与新鲜度可见

> 父计划：`specs/057-execution-decision-loop/plan.md`（节点一出口判据：静态列与实时指标列分界清晰；覆盖率、未匹配清单与新鲜度可见）
> 分支：`083-pretrade-live-columns`（worktree `../EMSXView-wt-083-pretrade-live-columns`，基线 082）
> 依赖：082（payload 扩字段）、DL-15（`GET /api/market-state/snapshot`，开关默认关闭）
> 状态：按目标指令直接实施；呈现细节按 D-6 与用户打磨后定稿

## 1. 问题（是什么）

DL-14 的盘前单表格是 9 列平铺：订单要素、日度基线、预期成本与缺口混在一起，看不出「哪些列随盘口实时变化」；082 新增的覆盖率/未匹配/新鲜度没有任何前端呈现；DL-15 的盘中状态端点无前端消费。

## 2. 方案（为什么这样做）

- **列分组 + 竖线分界**：`Order (static)` / `Daily baseline` / `Live intraday` / `Estimate` 四个分组表头，组间用 `border-l` 画分界，一眼区分「下达时已定」与「盘中在变」。
- **实时列数据源**：`GET /api/market-state/snapshot`（复用后端订阅，不新增行情调用）；30s 低频拉取 + 手动刷新；开关关闭或该票缺失一律显示 `n/a`，不猜数。
- **覆盖率/来源条**：`intent {source} · {pct}%`、`snapshot {formal|intraday|none}`、`live off|N live` 三个 chip；覆盖率 <100% 用琥珀色。
- **新鲜度条**：逐数据集 `dataset · 5m`，滞后 >30 分钟或未知（-1）标琥珀；tooltip 给 as_of。
- **未匹配清单**：可折叠 `<details>` 表格，列 Code / Order key / PM note / Reason。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `MarketView/module/types.ts` | 改 | `OrderIntentSource/SnapshotSource/UnmatchedIntent/FreshnessEntry` + payload 扩字段；`MarketStateSnapshot` 类型 |
| 2 | `MarketView/module/services/api.ts` | 改 | `fetchMarketStateSnapshot()` |
| 3 | `MarketView/module/components/pre-trade-board-panel.tsx` | 改 | 分组表头、实时列、状态 chip、新鲜度条、未匹配清单 |
| 4 | `MarketView/module/components/pre-trade-board-panel.test.tsx` | 改 | 来源/覆盖率/新鲜度/未匹配/实时两态 |
| 5 | `specs/057-execution-decision-loop/tasks.md` | 改 | 补 083 |

## 4. 验收（节点一出口判据）

1. 表格分组边界可见（四组表头 + 组间竖线），静态/日度/实时/估算不混排；
2. 覆盖率、意图来源、快照来源、实时开关状态在一行内可见；
3. 新鲜度逐数据集显示滞后，未知显式 `unknown`；
4. 未匹配清单可展开，reason 明确；
5. 实时关闭时全部显示 `n/a` 且页面不报错；打开时显示 Last / Spread bps / Vol vs base；
6. `vitest` 面板 6 例 + `tsc` 通过。
