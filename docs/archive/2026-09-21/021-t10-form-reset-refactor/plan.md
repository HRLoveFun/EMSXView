# 021 — T10 表单回填重构（key 重挂载）+ 前端 lint 接入 CI

> 特性：`021-t10-form-reset-refactor`
> 分支：`021-t10-form-reset-refactor`（worktree `../EMSXView-wt-021-t10-form-reset-refactor`）
> 上游：`specs/020-react-hooks-set-state-debt`（清零 18 条并登记 T10）
> 本 PR 同时回答 020 提出的「是否把 lint 接入 CI」

---

## 1. T10 的 4 处重构

问题模式：**「打开 / 切换目标时回填表单」用 effect 同步 setState 实现** —— 触发级联渲染，
且「打开」这一事件语义被拆散在 effect 依赖里。React 官方修法：**用 key 重置 state**（重挂载）+ 各 state 初值取自 props。

| # | 位置 | 改动 |
|---|---|---|
| 1 | `ExecutionView/module/components/unified-modify-route-dialog.tsx` | 删除「Reset on open」effect；新增 `initial`（8 个字段取自 `route`），`amount/orderType/…` 及 `orig*`（脏值对比基线）初值取自 `initial`；`orig*` 与只读的 `broker` 改为常量（生命周期内不变）；assetClass 的同步回落改为「初值即 `'EQTY'`」；调用方 `RouteTable.tsx` 注入 `key={路由id}:{open}` |
| 2 | `ExecutionView/module/components/route-plan-manager.tsx` | 删除 41 行「Reset form on open/edit」effect；15 个字段的 `useState` 初值改为 `editPlan?.x ?? 默认值`；只读的 `description` / `matchExchange` 改为常量；`RoutePlanManager` 渲染 `RoutePlanDialog` 时注入 `key={editPlan?.id ?? 'new'}:{open}` |
| 3 | `route-plan-manager.tsx`（券商选项） | 删掉 effect 内 `if (!matchMarket) { setAvailableBrokers([]); return; }`，改为读侧派生 `const brokerOptions = matchMarket ? availableBrokers : []`，并替换 3 处 `.length` + 1 处 `.map` 的读取点 |
| 4 | `route-plan-manager.tsx` | 为测试导出 `RoutePlanDialog`（生产路径仍只由 `RoutePlanManager` 渲染），注释说明用途 |

**行为等价性**：原先 effect 的触发条件是「`open`/`route`(或 `editPlan`) 变化即回填」；现在 key 覆盖
`{目标 id}:{open}`，即「每次针对某目标打开都重挂载」→ 表单回到该目标的值（新建则默认值）✓ 完全对齐。
`open=false` 时的重挂载只影响一个不渲染的子树，无副作用。

## 2. 新增契约测试（5 条）

| 文件 | 断言 |
|---|---|
| `ExecutionView/module/components/unified-modify-route-dialog.test.tsx` | ① 打开时以 `route` 原值预填（Qty / Limit Price）；② 切换路由（key 变化）后表单回到新路由原值、旧值不再出现 |
| `ExecutionView/module/components/route-plan-manager.test.tsx` | ① 编辑既有计划预填该计划值；② 新建（`editPlan=null`）用默认值、不留上次输入；③ 切换编辑目标后回到新目标值 |

两处测试都刻意针对「key 重挂载」这一契约：**若有人把回填改回 effect，或去掉调用方的 key，测试即失败**。

## 3. 前端 lint 接入 CI（问答 020 的「决定」）

**决定：接入，并且两条命令都接。**

- 先决条件已满足：模块 lint 18 → 0（020）、壳层 lint 2 → 0（本 PR）。
- 本 PR 顺带清掉壳层那 2 条（均在 `frontend/src/shared/hooks/use-startup-status.ts`）：
  - `react-hooks/purity`（`useRef(Date.now())` 在渲染期调用不纯函数）→ 改为 `useRef(0)` + effect 内落定起始时刻；
  - `set-state-in-effect`（`!enabled` 时的同步清空）→ 改为返回值派生，与 020 中 `use-execution-view-data` 同一手法。
- CI（`.github/workflows/boundary.yml` 的 `frontend-tests` job）新增两步：
  `npm run lint`（壳层/共享层）+ `npm run lint:modules`（三业务模块，模块代码不在 `frontend/` 内，
  默认 `eslint .` 扫不到，故必须分开）。
- 效果：**lint 红灯 = 新增违规**，债务不会再次无声累积。

## 4. 验收

| 项 | 结果 |
|---|---|
| `npm run lint`（壳层） | exit 0 |
| `npm run lint:modules`（三模块） | exit 0 |
| `npm run typecheck` | exit 0 |
| `npm test` | **23 文件 / 174 用例全绿**（较改造前 +2 文件 / +5 用例） |
| CI | 新增两步后全门禁 pass（见 PR checks） |

## 5. 风险与回退

- 风险集中在「回填时机」：已用 5 条契约测试锁定「预填 + 切换目标重置」两侧行为；其余 169 条既有用例覆盖消费方渲染。
- `use-startup-status` 的返回值派生使 `enabled=false` 时 `isChecking` 返回 `false`（原先可能残留上一次的 `true`）——按语义是修正，消费者（`AppShell` / `ExecutionModule`）行为不变。
- 回退：单一提交，`git revert` 即恢复。

## 6. 本次不做

- 020 遗留的 **T11**（6 处「与外部系统同步」类 fetch 豁免复核）：需数据层（react-query 等）方案，仍保持豁免 + 注释。
