# 022 — T11：仓库内取数层 `useAsyncData`，消除 5 处 fetch 豁免（第 6 处转 T12）

> 特性：`022-t11-async-data-layer`
> 分支：`022-t11-async-data-layer`（worktree `../EMSXView-wt-022-t11-async-data-layer`）
> 上游：`specs/020-react-hooks-set-state-debt`（登记 T11）、`specs/021-t10-form-reset-refactor`（T10 + lint 接入 CI）

---

## 1. 问题

020 清偿 lint 债务时，6 处「挂载/参数变化时拉取远端数据」按「与外部系统同步」保留了**局部豁免**（T11 待复核）。
它们共同的形状是：

```ts
useEffect(() => {
  setIsLoading(true);            // ← effect 同步体 setState ⇒ react-hooks/set-state-in-effect
  void load(deps);               // 命中点
}, [deps]);
```

## 2. 决策：仓库内最小取数层（**不引入外部依赖**）

`frontend/src/shared/hooks/use-async-data.ts`，按规则允许的形态实现：

- **loading 由 key 派生**（`isFresh = 结果属于当前 key 且属于当前 reload 轮次`）→ 不在 effect 内 setState；
- **setState 只出现在 Promise 回调中**（规则明确允许「订阅外部来源并在其回调里 setState」）；
- 旧请求用 `cancelled` 丢弃；`key === null` 表示本次不拉取（如对话框关闭）；
- 可选 `onData`：数据到达回调（供「取到数据后落本地可编辑 state / 触发 best-effort 落库」等场景）；
- loader 约定为**纯取数**（内部不得 setState）—— 这正是本层存在的意义。

API：`useAsyncData(key, loader, onData?) → { data, error, isLoading, reload }`

### 为什么不是 react-query
T11 原备注写的是「若引入数据层（如 react-query）」。评估后改走仓库内实现：本项目只有
「按 key 取一次 + 手动重取」这一种用法，引入外部依赖（缓存策略/DevTools/失效语义）与其收益不成比例；
本层 60 行、可测、零依赖，且**恰好**落在 lint 规则允许的形态上。

## 3. 落地（5 处豁免全部消除）

| # | 位置 | 改造 |
|---|---|---|
| 1 | `CostView/components/MonitoringView.tsx` | key = `lastPreset`（仅预设变化重取，指标勾选仍由热力图客户端过滤）；`health/coverage/error/isLoading` 改由 hook 派生；Refresh 按钮 → `reload` |
| 2 | `CostView/components/ReportView.tsx` | 三个 loader（meta/report/health）收敛为**一个纯取数** `fetchReportPayload` + `applyReportPayload`；首屏走 hook，**「生成报告」按钮**变为「事件回调 + `.then(applyReportPayload)`」；忙碌态/错误位合并（`busy` / `loadError`） |
| 3 | `ExecutionView/components/broker-strategy-fields.tsx` | key = `broker\|strategy\|assetClass`；字段（可编辑）由 `onData: setFields` 落定；`refresh()` 用 `forceRef` 保留「绕过缓存」语义 |
| 4 | `ExecutionView/components/market-broker-mapping-section.tsx` | 纯取数 + `onData`（含 best-effort 自动落库，改为 Promise 回调链）；网络异常在 loader 内收敛为 `errorMessage`，避免双错误通道；Refresh → `reload` |
| 5 | `ExecutionView/components/rate-diagnostic-dialog.tsx` | key = `open ? 'rate-diagnostic' : null`；自动展开改在 `onData` 内；重试按钮 → `reload` |

### 行为差异（已在 PR 中明示）
- 4 号：失败时 `state` 不再被「默认映射」覆盖（原先失败也合并默认值）；其余语义不变。
- 5 号：重新打开对话框会重新拉取（原先 `!data` 守卫下不重取）——按「打开即取最新诊断」更合理。

## 4. 第 6 处（`use-batch-route-state.ts` 的对账）转 T12 —— 及为什么

该处不是取数，而是**「父级订单列表刷新后与行状态对账」**（新增行补默认值、消失行剔除）。
正确修法是把它变成派生：`rows = buildRows(orders, rowPatch)`，用户编辑只写 `rowPatch`；
但 `rows` 在 700 行 hook 内被 ~15 处读写，其中 ~10 处 updater 依赖「`prev[oid]` 已有默认值」的假设，
需逐处改为读取派生值。

**关键事实**：`use-batch-route-state.ts` 目前**零测试覆盖**（`BatchOperationPanel.test.tsx` 仅 68 行，
不涉及 batch-route）。在无测试网的情况下重写其状态所有权，违背「行为保全优先」红线 —— 故本轮**保留豁免并升级理由**
（reducer 无变化时返回同一引用，React 跳过重渲染，无级联渲染开销），登记 **T12**：先补 hook 级测试，再做派生重构。

## 5. 验收

| 项 | 结果 |
|---|---|
| `npm run lint`（壳层） | exit 0 |
| `npm run lint:modules`（三模块） | exit 0，**fetch 类豁免 5 处全部删除**（剩余 1 处见 §4） |
| `npm run typecheck` | exit 0 |
| `npm test` | **24 文件 / 181 用例全绿**（+1 文件 / +7 用例 = hook 契约测试；既有 174 条无回归） |
| 新增测试 | `frontend/src/shared/hooks/use-async-data.test.tsx`：首载态 / key 变化重取 / key=null 跳过 / reload / 错误（含非 Error 包装）/ onData 时机 / 旧请求结果被丢弃 |

## 6. 本次不做

- T12（对账派生重构，见 §4）。
- 不为 hook 增加缓存/去重/重试策略（当前无此需求，保持最小）。
