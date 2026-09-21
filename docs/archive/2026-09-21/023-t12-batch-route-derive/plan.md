# 023 — T12 第一步：为 `useBatchRouteState` 补 hook 级测试（为 rows 派生化铺路）

> 特性：`023-t12-batch-route-derive`
> 分支：`023-t12-batch-route-derive`（worktree `../EMSXView-wt-023-t12-batch-route-derive`）
> 上游：`specs/022-t11-async-data-layer` §4（第 6 处豁免转 T12，前置条件是先补测试网）

---

## 1. 背景

022 清偿了 5 处 fetch 类 `set-state-in-effect` 豁免，第 6 处 ——
`batch-route-order/use-batch-route-state.ts` 的「父级订单列表刷新后与行状态对账」——保留豁免并转 T12，
理由是：**该 hook 约 700 行、目前零测试覆盖**，在无测试网的情况下重写状态所有权违背「行为保全优先」。
（`BatchOperationPanel.test.tsx` 仅 68 行、不涉及 batch-route。）

本 PR 完成 T12 的第一步：**先把行为钉住**。

## 2. 被锁定的语义（当前行为，不是期望行为）

| # | 场景 | 行为 |
|---|---|---|
| 1 | 打开对话框（`open` false→true） | 每个订单一行，`selected: true` |
| 2 | 父列表**新增**订单 | 补行，且 `selected: false`（与打开时不同！） |
| 3 | 父列表**移除**订单 | 该行剔除 |
| 4 | 用户改动（取消选中 / 分配数量）后在列表刷新时 | **保留**（对账只做增删，不覆盖） |
| 5 | 选中 broker | 每行补齐该 broker 的分配槽（`qty:'0'`）；取消选择则槽移除 |
| 6 | `open=false` | 不做对账 |

其中 **1 与 2 的默认值不同**（打开时全部选中、后来者不选中）是派生化重构的关键约束：
「默认是否选中」取决于**该订单是否在打开时就存在**，因此派生时需要保留"打开时的订单集合"这一事实。

## 3. 新增测试

`ExecutionView/module/components/batch-route-order/use-batch-route-state.test.tsx`（6 条，见上表）。
用 `renderHook` 直接驱动 hook，不依赖 UI，避免牵扯批量下单对话框的复杂渲染。

## 4. 下一步（T12 第二步，不在本 PR）

把 `rows` 派生化：

```
rowPatch（用户编辑，唯一可写状态）
   ↓ 派生
rows = { [o.id]: { selected: rowPatch[o.id]?.selected ?? openOrderIds.has(o.id),
                   allocations: buildAllocs(o.id, rowPatch, selectedBrokers) } }
```

涉及约 10 处 updater 从 `setRows(prev => ...prev[oid]...)` 改为读派生值，
并需要处理第 2 个 effect 里混在 `setRows` updater 内的**副作用**（`paramsBuildersRef` 清理，
在 StrictMode 下会被执行两次，属既有隐患，应一并移出）。

## 5. 验收

| 项 | 结果 |
|---|---|
| 新增 6 条 hook 测试 | 本地 + CI 全绿（锁定的语义与实现一致） |
| `npm run lint:modules` | exit 0（新增测试文件纳入 lint） |
| `npm run typecheck` | exit 0 |
| `npm test` | 全量无回归 |

## 6. 环境备注（本地，不影响仓库）

本 worktree 的 `npm ci` 被中断过一次，重装时触发了环境的批量删除保护
（`[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED]`）；对 023 而言不影响交付物
（CI 在干净环境用 `npm ci` 验证），仅本地验证耗时更长。
