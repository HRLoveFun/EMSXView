# 024 — T12 第二步：`rows` 派生化（消灭最后一处 `set-state-in-effect` 对账豁免）

> 特性：`024-t12-rows-derive`
> 分支：`024-t12-rows-derive`（worktree `../EMSXView-wt-024-t12-rows-derive`）
> 上游：`specs/023-t12-batch-route-derive`（第一步：先补 6 条 hook 级测试锁定对账语义）

---

## 1. 做法：写入口保留、读取改为派生视图

`use-batch-route-state.ts` 的两个对账 effect（「订单列表刷新补/删行」「券商变化补/剪分配槽」）
此前是 `setRows(prev => reconcile(...))`，命中 `react-hooks/set-state-in-effect`。本轮改为：

```
可写状态 rowState（打开时初始化 + 用户编辑 + 校验/提交结果回填）
        ↓ useMemo 派生
rows 视图 = { [o.id]: { selected: rowState[o.id]?.selected ?? false,
                        allocations: { [每个已选 broker]: rowState[o.id]?.allocations[b] ?? {qty:'0',violations:[]} } } }
```

**不变量改由读侧保证**（原由 effect 维持）：

1. 每个订单都有一行（列表新增自动出现；消失的自动不出现）；
2. 只含当前选中的 broker；
3. 缺省值补齐为 `{ qty:'0', violations: [] }`；
4. 「打开时存在的订单默认选中」仍由打开时的 `setRows(init)` 承担。

窗口的**写入**改为以派生视图为基准（否则新订单尚未写入 `rowState` 会导致编辑丢失）：

| 写入口 | 处理 |
|---|---|
| `patchRow` | `{ ...(prev[oid] ?? rows[oid]), ...patch }` |
| `patchAlloc` | 以 `rows[oid]` 为基准合并（原先 `if (!prev[oid]) return` 会吞掉新行的编辑） |
| 三个批量填充（`applyPercentQty` / `applyPercentToBroker` / `applyRatios`） | 迭代 `Object.entries(rows)`（新增订单也纳入） |
| `applyResults`（提交结果回填） | `next[oid] ?? rows[oid]` 兜底 |
| `toggleBroker`（取消勾选） | 事件回调内清掉各行该券商的槽，避免重新勾选时旧数量复活 |
| 保留的 effect | 只做与 React 无关的 `paramsBuildersRef` 附带清理（无 setState，规则允许） |

## 2. 两处**有意的行为变化**（023 的锁定测试当场抓出）

| # | 变化 | 判断 |
|---|---|---|
| 1 | 列表**新增订单**现在立刻带上已选券商的分配槽（此前要等 `selectedBrokers` 再变化才补） | ✅ 修正不对称（023 已记为「派生化时可一并修正」），测试已改为锁定新行为 |
| 2 | `rows` 视图不再受 `open` 门控（`open` 只控制「打开时的重置」） | ✅ 视图是 orders × rowState 的纯函数；关闭时组件不渲染，重新打开时 reset effect 会重新初始化，等价且更简单 |

另：023 的「选中 broker」用例实际是用 `undefined` 当券商（`allBrokers` 依赖后端目录，测试环境为空），
断言恒真 —— 本 PR 补齐 `useBrokerAlgorithms` / `useMarketBrokerMapping` 的 mock，使该用例真正生效。

## 3. 验收

| 项 | 结果 |
|---|---|
| `npm run lint`（壳层） | exit 0 |
| `npm run lint:modules`（三模块） | exit 0 —— **`set-state-in-effect` 豁免在本文件彻底消失** |
| `npm run typecheck` | exit 0 |
| `npm test` | **25 文件 / 187 用例全绿**（含 023 的 6 条对账测试；其中 2 条按 §2 更新预期） |
| CI | 全门禁 pass |

## 4. 遗留（不阻塞）

- `rowState` 中已消失订单的残留行不再被主动清除（视图不受影响，规模有界）。若将来要收敛，
  可在「打开时初始化」处顺带清理 —— 属清理优化，不影响正确性。
- **全仓库 `set-state-in-effect` 豁免收敛到 1 处**（`grep -n set-state-in-effect` 实测）：
  `ExecutionView/module/components/unified-modify-route-dialog.tsx:208`（broker 变化时拉取策略列表，
  属「与外部系统同步」类，已带理由注释）。其余 5 处 fetch 类豁免已在 022 的 `useAsyncData` 重构中删除。
