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
ExecutionView/                    # 仓库根级独立模块目录
├── README.md                     # 本文件：职责边界 / 接口 / 运行方式
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

本模块源码位于仓库根，但**依赖 `frontend/` 提供工具链与共享契约层**（`@shared/*`、`@/components/ui/*`、React 运行时）：

```bash
# 1) 依赖只需在 frontend/ 安装一次（模块不再自带 node_modules，避免出现第二份 React）
cd frontend
npm install
# ↑ postinstall 会自动执行 scripts/devtools/link-module-deps.mjs，
#   在仓库根建立 node_modules → frontend/node_modules 的链接。
#   原因：Node / TS / Vite 解析裸包（react、lucide-react…）是从引用方所在目录逐级向上查找
#   node_modules；本模块位于仓库根级目录，仓库根没有该链接时裸包解析会失败。

# 2) 随 Shell 一起开发（Vite dev server，端口 <FRONTEND_PORT> 默认 5173）
npm run dev

# 3) 随 Shell 一起构建（同一产物、同一套部署）
npm run build

# 4) 仅构建 ExecutionView 独立产物（输出 frontend/dist/execution/）
npm run build:execution
```

独立产物启动后为「无 Shell 桩」模式：`navigateTo` / `logout` 为空实现，toast 打到控制台。

## Testing

```bash
cd frontend
npx vitest run ../ExecutionView/module/ExecutionModule.test.tsx   # 仅本模块
npx vitest run                                                    # 全量（已含本模块）
npx tsc -b                                                        # 类型检查（含 ../ExecutionView）
npm run lint:modules                                              # ESLint（frontend 之外的模块源码）
```

> `npm run lint`（`eslint .`）只覆盖 `frontend/`；本模块源码在 `frontend/` 之外，
> ESLint 需从仓库根以显式配置运行，故另设 `lint:modules`。

## Dependencies

- `frontend/` 的工具链与运行时依赖（React 19 / Vite / Vitest / Tailwind / shadcn-ui）
- `@shared/*` 契约层：`module-registry`、`shell-context`、`services/*`、`types`
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
*Last verified: 2026-09-16（迁移见 [specs/012-executionview-root-extract/plan.md](../specs/012-executionview-root-extract/plan.md)；`ExecutionView` 不携带自有 `package.json`，工具链与依赖统一由 `frontend/` 提供。）*
