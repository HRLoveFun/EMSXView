# 011 — ExecutionView 模块独立化收口（职责边界 + 接口契约 + 独立测试）

> 特性：`011-executionview-module-contract`
> 分支：`011-executionview-module-contract`（worktree `../EMSXView-wt-011-executionview-module-contract`）
> 定位：把 ExecutionView 的「物理目录独立」推进到「契约独立」——显式接口、零隐式依赖、可独立测试。
> 依据：`.codebuddy/rules/module-boundary.md`、`.codebuddy/rules/coding-style.md`、[ADR-0008](../docs/spec/adr/0008-frontend-module-registry-pattern.md)

---

## 1. 现状评估（目标对照）

| 目标 | 现状 | 结论 |
|---|---|---|
| 独立成一个模块 | `frontend/src/modules/execution/` 已按 `module.registry.ts` 自注册，Shell 经 `moduleRegistry` 动态加载 | ✅ 物理独立已达成 |
| 封装数据获取/状态管理/渲染/事件处理 | `hooks/`（数据与域状态）、`services/`（API）、`stores/`（流增量）、`views/`（渲染）、`components/`（交互）分层齐备 | ✅ 已封装 |
| 明确职责边界与接口定义 | 输入 `ModuleShellProps`、输出 `onContribute` 负载仅隐含在 `ExecutionModule.tsx` 组件签名中；边界文档缺该模块条目 | ❌ 缺口 1 |
| 与其他模块低耦合 | 对 costview/marketview 无 import；但 `ExecutionModule.tsx` 反向 `import '@app/hooks/use-startup-status'`（模块 → Shell 层） | ❌ 缺口 2 |
| 独立测试覆盖核心功能路径 | 9 个测试偏组件/纯逻辑；模块编排层（数据源优先级、页签状态、贡献上报、预热降级）无测试 | ❌ 缺口 3 |
| 不影响现有功能 | — | 由门禁（tsc / vitest / boundaries）保证 |

---

## 2. 职责边界（What this module owns）

**拥有（Owner）**：ExecutionView 工作区的全部前端逻辑

- 数据获取：`services/orders-api | routes-api | route-plans-api | broker-api`，实时流 `hooks/use-orders-stream | use-routes-stream` + `stores/*-stream-store`，降级轮询 `hooks/use-execution-poller`
- 状态管理：`hooks/use-execution-view-data`（服务端数据 + 选择态）、`hooks/use-execution-state`（页签 / 筛选 / Monitor 条件）
- 渲染：`views/ExecutionViewTabs` → `MonitorBoard | ExecutionBoard | SubOrderReviewPanel | SettingsBoard`
- 事件处理：`hooks/use-execution-mutations`（下单/改单/改路由/撤路由）、`hooks/use-trade-hotkeys`、`hooks/use-board-navigation`
- 数据域：`execution_state`（订单/路由运行态），见 `platform_data/contracts/boundary_registry.py`

**不拥有（Not Owner）**：

- 交易成本分析与报告 → CostView；盘前市场数据 → MarketView；数据库维护 → 独立仓库 EMSXDataPipeline Runner
- 实时连接生命周期与重连 → Shell（模块只声明 `realtimeWsPath`，不自行 `new WebSocket`）
- 跨模块交接合约存储 → `platform_data` 适配器

---

## 3. 输入 / 输出接口契约

契约文件：`frontend/src/modules/execution/module.contract.ts`

| 方向 | 类型 | 说明 |
|---|---|---|
| Shell → 模块 | `ExecutionModuleProps`（= `ModuleShellProps`） | `onContribute?` 上报通道；其余宿主能力经 `useShellContext()` 获取 |
| 模块 → Shell | `ExecutionModuleContribution` | `counts: { orders, routes }`、`isLoading`、`lastUpdatedAt`、`refresh()`、`clearCache()` |
| 模块 → 子视图 | 各视图 props（模块内部契约，不对外） | 例：`MonitorBoard` 收 `allOrders / allRoutes / conditions / onConditionsChange` |

不变式：

1. 模块外代码**不得** import `@execution/*` 深层路径；唯一合法耦合是 Shell 的 `moduleRegistry` 描述符。
2. 模块**不得** import `@app/*`；宿主能力一律经 `@shared/lib/shell-context`。
3. 上报负载由 `ExecutionModuleContribution` 编译期约束，Shell 侧按 `ModuleContribution` 消费，二者不因模块内部字段调整而漂移。

---

## 4. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `frontend/src/modules/execution/module.contract.ts` | 新增：模块输入/输出接口契约 |
| 2 | `frontend/src/modules/execution/ExecutionModule.tsx` | 消费契约类型；删除组件内隐式 `ExecutionModuleInfo`；改用 `@shared/hooks/use-startup-status` |
| 3 | `frontend/src/app/hooks/use-startup-status.ts` → `frontend/src/shared/hooks/use-startup-status.ts` | 上移：被 Shell 与 execution 模块共用，按 coding-style「跨模块共享上移」归 `@shared` |
| 4 | `frontend/src/app/AppShell.tsx` | 同步引用路径 |
| 5 | `frontend/src/modules/execution/ExecutionModule.test.tsx` | 新增：模块独立测试（5 条核心路径） |
| 6 | `backend/api/tests/boundaries/test_cross_module_imports.py` | 新增规则：execution → `@app` 禁止（`.tsx` / `.ts`） |
| 7 | `platform_data/contracts/boundary_registry.py` | `frontend_execution.forbidden_imports` 增 `@app` |
| 8 | `.codebuddy/rules/module-boundary.md` | 新增 §1.7 execution ↔ Shell 五元组规则 |
| 9 | `docs/spec/project-structure.md` | 模块结构补记契约文件 |

---

## 5. 验收矩阵（改动 ↔ 需求双向映射）

| 需求 | 覆盖改动 | 检验方法 |
|---|---|---|
| 独立成一个模块 | —（已达成，本计划固化） | `module.registry.ts` 自注册；`audit_cross_imports.py --module frontend_execution` |
| 封装全部相关逻辑 | 1、2 | `npx tsc --noEmit` + 模块目录分层不变 |
| 明确职责边界与接口定义 | 1、8、9 | 契约文件 + 边界文档五元组；`test_no_forbidden_imports` |
| 与其他模块低耦合 | 3、4、6、7 | `rg "from ['\"]@app" frontend/src/modules/execution/` 零命中 |
| 独立测试覆盖核心路径 | 5 | `npx vitest run src/modules/execution/ExecutionModule.test.tsx` |
| 不影响现有功能 | 全部 | `npx vitest run`（全量前端）+ `pytest backend/api/tests/boundaries/` |

核心路径覆盖清单（测试 → 路径）：

| 测试用例 | 覆盖路径 |
|---|---|
| 默认激活 Monitor 并透传数据 | 数据获取 → 渲染 |
| 页签切换渲染对应视图 | 状态管理 + 事件处理 |
| 按契约上报贡献信息 | 模块输出接口 |
| 实时流优先于 REST 快照 | 数据源优先级 |
| 预热三态降级提示 | 异常/降级路径 |

---

## 6. 门禁与风险

- **门禁**：`npx tsc --noEmit`、`npx vitest run`、`pytest backend/api/tests/boundaries/`、`python scripts/audit_cross_imports.py`。
- **风险**：`use-startup-status` 上移属跨目录重命名，git 可识别为 rename；回滚路径为 revert 该提交。
- **不做**：不拆分 `views/` 子域（monitor/trade/route-engine/settings）为独立模块——属重构专项，不在本次范围。
