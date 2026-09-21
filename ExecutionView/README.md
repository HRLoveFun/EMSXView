# ExecutionView Module

> **Post-Trade Order & Route Execution Workspace** · 🟢 **GA** · 仓库根级独立前端模块

> 成熟度分级定义见主 [README.md §0](../README.md#0-模块成熟度分级契约定义)。本目录与 `frontend/`、`backend/`、`CostView/`、`MarketView/` 平级，不再嵌套在 `frontend/src/modules/` 之内。

---

## Overview

**ExecutionView** 提供实时订单与路由管理工作区（Bloomberg EMSX）：

- **Monitor** —— 按条件分组展示异常订单
- **Trade** —— 订单表 / 路由表 / 批量操作 / 快捷键导航
- **Route Engine** —— 子单与路由建议审核
- **Settings** —— Monitor 条件、Broker 算法、参数频率、策略数据、路由计划模板、Market↔Broker 映射

数据经 `backend/api`（Core `<API_PORT>`，默认 3000）的 REST 与 `/ws/orders` 实时流获取。

## Architecture

```
ExecutionView/                    # 仓库根级独立模块目录（npm workspaces 成员）
├── README.md                     # 本文件：职责边界 / 接口 / 运行方式
├── package.json                  # ★ 自带依赖声明（react / react-dom / lucide-react + 测试期依赖）
├── module/                       # 模块实现（原 frontend/src/modules/execution/）
│   ├── module.registry.ts        # 自注册描述符（id/label/order/loader/realtimeWsPath/showHandoffBadge）
│   ├── module.contract.ts        # ★ 对外接口契约（输入 ExecutionModuleProps / 输出 ExecutionModuleContribution）
│   ├── ExecutionModule.tsx       # 模块根组件（编排数据 → 状态 → 渲染 → 上报）
│   ├── components/               # 交互组件（对话框 / 菜单 / 批量下单 / 过滤器）
│   ├── hooks/                    # 数据获取、域状态、实时流、变更回调
│   ├── views/                    # MonitorBoard / ExecutionBoard / ExecutionViewTabs / settings
│   ├── services/                 # REST API 客户端
│   ├── stores/                   # 订单 / 路由实时流 store
│   ├── types/ lib/ data/         # 域模型、纯逻辑工具、映射常量
│   └── **/*.test.{ts,tsx}        # 模块独立测试
└── standalone/                   # 独立构建入口（index.html + main.tsx）
```

## Responsibilities（职责边界）

**Owner（本模块拥有）**：ExecutionView 工作区的前端逻辑

- 数据获取：订单 / 路由 / broker / 路由计划的 REST 客户端，`/ws/orders` 实时流与断流降级轮询
- 状态管理：服务端数据、选择态、页签、筛选、Monitor 条件
- 渲染与事件处理：四个视图、批量操作、下单/改单/改路由/撤路由、快捷键
- 数据域：`execution_state`（订单与路由运行态），见 [`platform_data/contracts/boundary_registry.py`](../platform_data/contracts/boundary_registry.py)

**Not Owner（不拥有）**

- 交易成本分析与报告 → CostView；盘前市场数据 → MarketView；数据库维护 → 独立仓库 EMSXDataPipeline Runner
- 实时连接生命周期与重连 → Shell（本模块只声明 `realtimeWsPath`，不自行 `new WebSocket`）
- 跨模块交接合约存储 → `platform_data` 适配器

## Interface（对外接口契约）

契约唯一定义在 [`module/module.contract.ts`](./module/module.contract.ts)：

| 方向 | 类型 | 说明 |
|---|---|---|
| Shell → 模块 | `ExecutionModuleProps`（= 共享契约 `ModuleShellProps`） | 仅 `onContribute` 上报通道 |
| 模块 → Shell | `ExecutionModuleContribution` | `counts: { orders, routes }`、`isLoading`、`lastUpdatedAt`、`refresh()`、`clearCache()` |
| 模块 → Shell 宿主服务 | `useShellContext()`（`@shared/lib/shell-context`） | 导航 / toast / 实时连接状态 / logout |

约束（由 [`module-boundary.md §1.7`](../.codebuddy/rules/module-boundary.md) 与边界测试双重守护）：

- 模块外代码**不得** `import '@execution/*'` 深层路径；唯一合法耦合是 Shell 通过 `moduleRegistry` 读取注册描述符
- 本模块**不得** `import '@app/*'`（Shell 层）；宿主能力一律经 `@shared/lib/shell-context`
- 与 costview / marketview 的交互只能经 `navigateTo` / `useHandoffContracts()` / `@shared/types`

## Running & Building

本模块**自带依赖声明**（`ExecutionView/package.json`），工具链与共享契约层（`@shared/*`、`@/components/ui/*`）仍由 `frontend/` 提供；依赖树由 npm workspaces 统一提升到仓库根，全仓库只有一份 React：

```bash
# 1) 依赖在**仓库根**安装一次（npm workspaces: frontend + ExecutionView 共用依赖树与 lockfile）
cd <repo-root>
npm ci            # 或 npm install

# 2) 随 Shell 一起开发（Vite dev server，端口 <FRONTEND_PORT> 默认 5173）
cd frontend
npm run dev

# 3) 随 Shell 一起构建（同一产物、同一套部署）
npm run build

# 4) 仅构建 ExecutionView 独立产物（输出 frontend/dist-modules/execution/）
npm run build:execution
```

> 不要在 `frontend/` 内单独 `npm install`——那会在子目录建出第二份依赖树（第二份 React）。

独立产物启动后为「无 Shell 桩」模式：`navigateTo` / `logout` 为空实现，toast 打到控制台。

## Testing

```bash
# 在仓库根（workspaces 根）执行
npm test                        # 全量 vitest（含本模块）
npm run typecheck               # tsc -b（含 ../ExecutionView）
npm run lint:modules            # ESLint（frontend 之外的模块源码）

# 只跑本模块（在 frontend/ 下用 npm 脚本；不要用裸 npx —— 依赖已提升到仓库根，子目录没有 .bin）
cd frontend && npm test -- ../ExecutionView/module/ExecutionModule.test.tsx
```

> `npm run lint`（`eslint .`）只覆盖 `frontend/`；本模块源码在 `frontend/` 之外，
> ESLint 需从仓库根以显式配置运行，故另设 `lint:modules`。
> 注意：`lint:modules` 目前会报出 14 条 `react-hooks/*` 存量问题（`npm run lint` 在 `frontend/src` 同样报 6 条，
> 同源且均属既有债务，ESLint 不在 CI 门禁内）。跑测试不受影响；若要以 lint 作为门禁，需先清偿这批存量问题。

## Dependencies

- 自身声明：`ExecutionView/package.json` —— `react` / `react-dom` / `lucide-react`（运行时）+ `vitest` / `@testing-library/*`（测试期）
- `frontend/` 的工具链与共享契约层：`@shared/*`（`module-registry` / `shell-context` / `services/*` / `types`）、`@/components/ui/*`、Vite / Vitest / Tailwind / shadcn-ui
- 依赖树与唯一 lockfile 由仓库根 npm workspaces 统一管理（[ADR-0020](../docs/spec/adr/0020-frontend-npm-workspaces.md)），并显式配置 `resolve.dedupe: ['react','react-dom']`
- 后端 Core `<API_BASE_URL>`（默认 `http://<host>:3000`）与 `/ws/orders`
- 不使用 Bloomberg 直连（由后端 EMSX 服务承担）

## Data Flow

```
backend/api (Core :3000) ── REST /api/orders|routes|broker/*  ─┐
                          └─ WS  /ws/orders ──────────────────┤
                                                               v
ExecutionView/module/services + hooks/use-*-stream → stores/*-stream-store
                                                               v
                            ExecutionModule（状态编排）→ views/* 渲染
                                                               v
                          module.contract.ts（ExecutionModuleContribution）→ Shell 工具栏
```

---

*Status: 仓库根级独立模块（源码与独立构建入口均已迁出 `frontend/`）。*
*Last verified: 2026-09-16（迁出 frontend 见 [docs/archive/2026-09-21/012-executionview-root-extract/plan.md](../docs/archive/2026-09-21/012-executionview-root-extract/plan.md)；自带依赖声明与 workspaces 收敛见 [docs/archive/2026-09-21/013-frontend-workspaces/plan.md](../docs/archive/2026-09-21/013-frontend-workspaces/plan.md) / ADR-0020。工具链与共享契约层仍由 `frontend/` 提供。）*
