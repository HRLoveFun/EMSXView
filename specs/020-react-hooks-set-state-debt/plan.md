# 020 — 清偿 `react-hooks/set-state-in-effect` 存量债务（18 处）

> 特性：`020-react-hooks-set-state-debt`
> 分支：`020-react-hooks-set-state-debt`（worktree `../EMSXView-wt-020-react-hooks-set-state-debt`）
> 定位：P1 清单 #6；收尾 `specs/019`（路径清理）后的最后一项遗留
> 判定基线：`npm run lint:modules` → 改造前 **18 errors**，改造后 **0 errors**

---

## 1. 为什么值得做

`npm run lint:modules` 长期为红（18 条）。它不在 CI 门禁内，于是**任何新增违规都被淹没在存量噪声里**——
门禁价值为零。本轮把这 18 条逐条定性，能真改的真改、不能的写清理由，使该命令可用于「红灯即新增」。

规则语义（`eslint-plugin-react-hooks` v6 recommended）：effect 同步体内调用 `setState` 会引发级联渲染。
消解方式按 React 官方指引：**派生值** → **用 key 重置 state** → **事件回调**；仅当「与外部系统同步」
（挂载/参数变更时拉取远端数据）时才以局部豁免 + 理由保留。

## 2. 处置分类（18 处全量）

### 2.1 真改 8 处

| # | 位置 | 手法 | 行为等价性说明 |
|---|---|---|---|
| 1 | `CostView/ConfigureView.tsx:35` | 删除 effect；调用方 `key={config.updatedAt}` 重挂载（`CostViewModule.tsx:433`） | config 变更即重置草稿，与原 effect 同语义；React 官方「用 key 重置 state」 |
| 2 | `CostView/ReportView.tsx:441`（`react-hooks/refs`：渲染期读 ref） | 改 `useState(() => buildInitialReportForm())` 持有初值，删除 ref | 初值只构建一次；「重置」改用该 state 值，语义不变 |
| 3 | `MarketView/MarketViewModule.tsx:115` | 把「快照刷新后修剪选中项」移入 fetch 的 `.then` 回调；失败分支同步清空 | setState 位于异步回调（规则允许）；等价于原 effect 的修剪 |
| 4 | `ExecutionView/algo-launch-dialog.tsx:84` | 删除 effect；调用方 `key={订单id}:{open}`（`ExecutionBoard.tsx:230`） | 「每次针对某订单打开即回填初始表单」等价 |
| 5 | `ExecutionView/order-modify-dialog.tsx:70` | 删除 effect；`useState` 惰性初值取自 `order`；调用方 `key={订单id}:{open}`（`OrderTable.tsx:706`） | 重挂载等价于原 `setUpdates(order 原值)` |
| 6 | `ExecutionView/views/settings/SettingsBoard.tsx:26` | 删除 effect；调用方 `key={initialSection}`（`ExecutionModule.tsx:206`） | prop 变化即回到该分区，等价 |
| 7 | `ExecutionView/hooks/use-execution-view-data.ts:131` | 未登录时的「清空」改为**返回值派生**（orders/routes/trader/selection/isLoading），effect 只复位 ref | 对消费者语义完全一致（未登录即无数据） |
| 8 | `ExecutionView/views/RouteTable.tsx:132` | 「乐观替换标记」按路由稳定态**读侧派生**（新增模块级 `STABLE_ROUTE_STATUSES`），effect 只做定时器清理 | 达到稳定态即视为清除，与原 effect 修剪 + 6s 兜底等价 |

### 2.2 保留并写清理由 10 处

**A. 「与外部系统同步」类（挂载/参数变更拉取远端数据，5 处）** —— 规则允许的 fetch 场景；同步置 loading/清空态是为立刻反馈，无法改写成派生值：

`MonitoringView.tsx:216`、`ReportView.tsx`（首屏 `loadReport/loadMeta/loadHealth`）、
`broker-strategy-fields.tsx:92`、`market-broker-mapping-section.tsx:142`、
`rate-diagnostic-dialog.tsx:106`、`unified-modify-route-dialog.tsx:214`

**B. 对账类（1 处）**：`batch-route-order/use-batch-route-state.ts:362` —— 父级订单列表刷新后与行状态对账；
reducer **无变化时返回同一引用**（`return changed ? next : prev`），React 会跳过重渲染，不存在级联渲染开销。

**C. 待重构（4 处，已登记 `docs/open-todos.md` T10）**：`route-plan-manager.tsx:270/319`、
`unified-modify-route-dialog.tsx:176/193` —— 理想修法是 `key` 重挂载 + state 初值取自 props，
但分别需一并改写 15 / 8 处 state 初值，改动面与风险超出本轮；已在代码内以 `TODO(specs/020)` 标注。

## 3. 验收

| 项 | 结果 |
|---|---|
| `npm run lint:modules`（三模块） | **18 errors → 0 errors** |
| `npm run typecheck` | exit 0 |
| `npm test` | **21 文件 / 169 用例全绿**（0 失败）—— 覆盖本轮触及的 CostView / MarketView / ExecutionView 组件与 hook |
| 豁免可审计 | 每条豁免均带「豁免理由 / 待重构」注释，无无条件 disable |

## 4. 风险与回退

- 风险点集中在 3 处「派生」改动（2.1 的 3、7、8）：已通过全量测试 + 类型检查；语义等价性逐条列在上表。
- 回退：单一提交，`git revert` 即恢复原状态。

## 5. 建议的后续

1. 完成 T10 的 4 处「回填表单」重构（可一并补组件测试）。
2. 把 `npm run lint:modules` 纳入 CI 前端 job —— 本轮之后它已是绿色，具备成为门禁的条件（属 CI 策略变更，未在本 PR 单方面改动）。
3. 若引入数据层（react-query 等），可消解 2.2-A 的 5 处豁免。
