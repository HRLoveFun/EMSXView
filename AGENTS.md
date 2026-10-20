# EMSXView — 仓库总览与 AI 代理指南

> **本文定位**：仓库唯一的 Agent 入口，同时承载项目总览（架构、模块、数据层）与作业规范（工作流、编码约定、构建与验证）。`README.md` 为面向人类读者的精简首页。
>
> **单一来源**：`AGENTS.md` 是仓库唯一的 Agent 规范源。原 `CODEBUDDY.md` 副本已于 2026-10-20 删除——pre-commit hook 不再做双份同步，文档漂移审计也不再校验两份一致性；需要引用规范时一律指向本文件。

---

## 目录

- [1. 文档阅读顺序（必读）](#1-文档阅读顺序必读)
- [2. 回复语言约定](#2-回复语言约定)
- [3. 占位符与可配置参数约定](#3-占位符与可配置参数约定)
- [4. 项目定位与模块成熟度](#4-项目定位与模块成熟度)
- [5. 架构总览](#5-架构总览)
- [6. 目录结构](#6-目录结构)
- [7. 关键开发约定](#7-关键开发约定)
- [8. 文件放置规范](#8-文件放置规范)
- [9. 启动器与项目根路径](#9-启动器与项目根路径)
- [10. Git 多任务并行工作流](#10-git-多任务并行工作流)
- [11. Build & Run Commands](#11-build--run-commands)
- [12. 验证与质量门禁](#12-验证与质量门禁)
- [13. 数据层与降级路径](#13-数据层与降级路径)
- [14. 已失效声明（勿再引用）](#14-已失效声明勿再引用)
- [15. 文档地图](#15-文档地图)

---

## 1. 文档阅读顺序（必读）

进入本仓库的 AI 代理 **必须** 按以下顺序阅读文档，再开始任何代码改动：

1. `AGENTS.md`（本文件）— 工作流、安全规则与项目总览
2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理
4. `.codebuddy/rules/module-boundary.md` — ★ 模块边界契约
5. `.codebuddy/rules/agent-workflow.md` — ★ Agent 作业节奏（等待 / 轮询一律每 5 秒一次）
6. `docs/spec/project-structure.md` — 当前仓库结构
7. `docs/spec/data-domain.md` — 数据域所有权
8. `docs/spec/memory.md` — 架构记忆入口（指向 ADR 列表）
9. `docs/spec/module-onboarding.md` — 新增模块流程
10. `docs/spec/anti-patterns.md` — ★ 禁止模式
11. `docs/spec/plan-design-principles.md` — ★ 计划设计原则
12. `docs/spec/refactoring-methodology.md` — ★ 系统性安全重构框架
13. `docs/spec/git-workflow.md` — Git 多任务并行工作流（多任务 / 多 Agent 并行前必读）

## 2. 回复语言约定

所有 AI 编码代理在与用户对话时，**必须使用中文回复**（代码、标识符、技术术语除外）；文档与代码注释使用中文。

**如实标注纪律**：能力描述必须可验证（入口 + 验证方式），禁止使用「production-ready」等无判据形容词——成熟度分级见 §4。

## 3. 占位符与可配置参数约定（★ 写文档前必读）

文档中出现的具体路径、主机、端口一律用**占位符**表达，禁止写入与本机绑定的硬编码值：

| 占位符 | 含义 | 默认值 / 真相源 |
|---|---|---|
| `<repo-root>` | 仓库根（由 `.emsxview-root` marker 定位） | 各机器克隆路径不同 |
| `${EMSXVIEW_DATA_DIR}` | 数据根 | 默认 `Config.DEFAULT_DATA_DIR`（见 `data_access/config.py`） |
| `<host>` | 服务主机名 | `localhost` |
| `<API_PORT>` / `<API_BASE_URL>` | 后端端口 / 基址 | `3000` / `http://<host>:3000`（`API_HOST`、`API_PORT`） |
| `<MARKETVIEW_PORT>` / `<MARKETVIEW_BASE_URL>` | MarketView | `8001`（`MARKETVIEW_HOST`、`MARKETVIEW_PORT`） |
| `<COSTVIEW_PORT>` / `<COSTVIEW_BASE_URL>` | CostView | `8002`（`COSTVIEW_HOST`、`COSTVIEW_PORT`） |
| `<FRONTEND_PORT>` | 前端开发服务端口 | `5173`（`vite --port`、`VITE_API_URL`） |
| `<POSTGRES_PORT>` / `<PROMETHEUS_PORT>` / `<GRAFANA_PORT>` | 容器宿主映射 | `5432` / `9090` / `3001` |

引用规则：**仓库内文件一律用仓库相对路径**（如 `data_access/config.py`）；仓库外资源（如已迁出的 EMSXDataPipeline）只说明归属，不写具体磁盘路径。完整约定见 [`docs/index.md` §7](docs/index.md#7-占位符与可配置参数约定)。

## 4. 项目定位与模块成熟度

**项目定位**：订单执行与交易成本分析（TCA）单体仓库——执行管理（ExecutionView）、盘前市场视图（MarketView）、盘后 TCA（CostView），共享一个 React 前端壳与一个只读数据访问层。

### 4.1 分级定义（契约）

本仓库所有模块使用以下统一分级，**禁止**在无证据的情况下宣称「production-ready」等无判定标准的形容词：

| 等级 | 含义 | 必须满足的证据 |
|------|------|----------------|
| **GA / 生产就绪** | 已在真实交易流程中使用 | 真实交易数据持续入库 + 自动化测试覆盖核心路径 + 运维手册存在 |
| **Beta** | 功能完整但未全量 | 单元/集成测试 + 已知限制清单（known limitations）公开发布 |
| **Scaffold / 骨架** | 仅有接口与占位 | 明确列出「未实现」清单 |

### 4.2 当前分级总表（2026-10-20 复核）

| 模块 | 等级 | 判定证据 | 已知欠缺 |
|------|------|----------|----------|
| **ExecutionView**（`backend/api/` + `ExecutionView/module/`） | **GA** | 真实成交数据持续入库（`raw_fills.db` 7.15 GB、`execution_history.db` 6.54 GB）；后端 45 个测试文件 / 295 个测试函数；运维手册 [docs/ops/service-management.md](docs/ops/service-management.md) | 无正式 SLA 文档；无独立端到端集成测试套件（依赖 mock Bloomberg） |
| **CostView**（`CostView/` + `CostView/module/`） | **Beta** | 10 个测试文件 / 305 个测试函数（含 CLI 入口与黄金样本回归）；14 个 API 端点全部可追溯到代码；已知限制清单 [docs/report-tca-known-limitations.md](docs/report-tca-known-limitations.md) | 覆盖率未量化（已配 coverage 但无 `--cov-fail-under` 门槛）；无模块专项运维手册（`docs/ops/` 未覆盖，故不进 GA） |
| **MarketView**（`MarketView/`） | **Scaffold** | 3 个端点（快照 / 盘中特征 / handoff 发布）；`MarketView/tests/` 已存在（1 个测试文件，覆盖三个端点） | 策略分析、选券支持、SLA/运维文档均未实现 |
| **frontend/**（React 壳） | **Beta** | 25 个前端测试文件（vitest）；三模块注册完整 | 覆盖率未量化 |
| **data_access/**（只读数据层） | **Beta** | 契约测试锁定两仓常量一致（`data_access/config.py` 模块 docstring）；`mode=ro` 连接层 | 无自身测试目录 |
| **platform_data/**（跨模块适配层） | **Beta（部分规划中）** | handoff/contracts/tests 均有实现 | 部分 Adapter 为规划中、尚未实现，见 [ADR-0013](docs/spec/adr/0013-platform-data-adapter-current-state.md)，禁止按符号 import |

## 5. 架构总览

### 5.1 运行时架构

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EMSXView Trading Platform                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐          │
│  │   MarketView     │──▶│  ExecutionView   │──▶│    CostView      │          │
│  │   (Pre-Trade)    │   │  (Order Exec)    │   │  (Post-Trade)    │          │
│  │  [Scaffold]      │   │  [GA]            │   │  [Beta]          │          │
│  │ :<MARKETVIEW_PORT>│  │  :<API_PORT>     │   │ :<COSTVIEW_PORT> │          │
│  └────────┬─────────┘   └───────┬──────────┘   └───────┬──────────┘          │
│           │                     │                      │                     │
│           ▼                     ▼                      ▼                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Shared Infrastructure                            │   │
│  │  frontend/ [Beta] (React shell) · platform_data/ [Beta] (adapters)    │   │
│  │  data_access/ [Beta] (read-only) · SQLite (只读, ~128 GB) ·           │   │
│  │  PostgreSQL (可选) · Redis (可选) · Nginx                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┄┄┄ 仓库外（独立仓库 EMSXDataPipeline）┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   │
│  数据管道 Runner（唯一写入方，本机 :8100）──写入──▶ ${EMSXVIEW_DATA_DIR}      │
└──────────────────────────────────────────────────────────────────────────────┘
```

箭头仅表示数据流向，**不表示能力对等**（MarketView 与 CostView 完成度不对等）。

```
MarketView (Pre-Trade) ──▶ ExecutionView (Order Execution) ──▶ CostView (Post-Trade TCA)
   [Scaffold]                   [GA]                              [Beta]
        │                          │                                │
  Market Snapshot            Orders & Routes                   TCA Analysis
  Intraday Features          Bloomberg EMSX API                Scorecard / Monitoring
  Handoff → Execution        Real-time WebSocket               Recommendations (pin)
```

### 5.2 部署形态

| Mode | 控制方式 | Architecture |
|------|----------|--------------|
| **Microservice**（默认） | 无需配置 | Core `<API_PORT>`、CostView `<COSTVIEW_PORT>` 独立进程 |
| **CostView 路由桥接**（可选） | `EMSXVIEW_OPTIONAL_MODULES`（默认 `costview:CostView`） | CostView 的 `/api/tca/*` 路由挂载进 core 进程（`backend/api/routers/costview.py`），前端经 `:3000` 单入口访问，无需启动 `:8002` |

- 可选模块白名单经 `EMSXVIEW_OPTIONAL_MODULES` 配置（`*` / `all` 加载全部，置空禁用），由 `backend/api/main.py` 的 `_register_optional` 加载。
- MarketView **没有**桥接路径，仅独立运行。
- 跨模块 handoff 后端由 `EMSXVIEW_HANDOFF_BACKEND` 选择：`memory`（默认，进程内 dict + 锁）或 `redis`（跨进程）；非法值启动即 `ValueError`（不静默降级）。

### 5.3 跨模块数据流

**Handoff 通道**（`platform_data/adapters/`）：

| 通道 | 方向 | 写入端点 | 读取端点 | 容量/时序语义 |
|------|------|----------|----------|----------------|
| Market → Execution | 单槽（仅保留最新一份） | `POST /api/marketview/handoff/execution` | ExecutionView 经 handoff API 读取 | 新写入覆盖旧值；无历史 |
| Execution → Cost | 按 order_id 映射 | ExecutionView 成交后写入 | `GET /api/tca/handoff/post-trade/{order_id}` | 上限 500 条，TTL 7 天惰性清理，超限淘汰最旧 |
| Cost → Execution（recommendations） | 追加列表 | `POST /api/tca/recommendations/pin` | `GET /api/broker-recommendations` | 上限 200 条，追加 + 截断，**last-write-wins** |

一致性语义（重要）：

- **同步拉取**：写入在请求内完成，读取方在自身请求内同步拉取，无推送订阅；前端经 `useHandoffContracts()` + `frontend/src/shared/services/handoff-api.ts` 按需读取。
- **可能读到过期结论**：条目 TTL 7 天，TTL 内的旧 recommendation 不会被自动失效——读到的是「最近一次 pin」，不保证反映最新分析。
- **无合并逻辑、无跨模块事务**：并发写入一律 last-write-wins，handoff 与业务写库互不原子。
- **Redis 后端**：3 个 key（`mv-to-ev` / `ev-to-cv` / `cv-to-ev`），`cv-to-ev` 列表上限 200（`rpush` + `ltrim`）；三通道均设 7 天 TTL（`pipeline` 内原子写入）。
- **载荷限制**：`strategy_params` ≤ 64 KB（`HANDOFF_MAX_STRATEGY_PARAMS_BYTES`），超限返回 422。

契约定义：[docs/schema-contract.md](docs/schema-contract.md)（Contract 1–4）。

**ETL 触发链**（跨仓库，CostView 是只读消费者）：

```
前端/脚本 ──POST /api/tca/runner/run (JWT 鉴权)──▶ backend :3000 ──代理──▶ EMSXDataPipeline Runner :8100 POST /run
                  GET /api/tca/runner/status ──────────────────────────▶ GET /status
```

- **职责归属**：数据更新（ETL 写入）唯一写入方是独立仓库 EMSXDataPipeline；本仓库**没有任何写库路径**（`data_access` 全部 `mode=ro`）。
- **入口**：`backend/api/routers/costview.py`（JWT 鉴权代理，前端统一经 `:3000`，不直连 Runner），Runner 地址由 `EMSXVIEW_RUNNER_URL` 配置。
- **失败处理**：Runner 不可达 → `ApiResponse(success=False, "Runner unreachable: ...")`；非 2xx / 非 JSON → 失败响应；代理不重试。
- **幂等性**：Runner 为单任务模型——已在运行时再次触发返回 409，代理转而返回当前 `/status` 结果 + `"pipeline already running"`，不并发重复执行。

## 6. 目录结构

```
EMSXView/
├── AGENTS.md                        # 本文件（Agent 入口 + 项目总览，唯一规范源）
├── README.md                        # 人类读者首页
├── QUICKSTART.md                    # 一键启动指南
├── relaunch_service.bat             # 一键重启
│
├── frontend/                        # ★ 规范 React 前端壳 [Beta]
│   ├── package.json                 # npm: emsxview-trading-tool
│   ├── vite.config.ts               # 主 Vite 配置（dev server <FRONTEND_PORT>）
│   ├── vite.base.ts                 # 独立模块构建基座（--module=<id> → dist-modules/<module>/）
│   └── src/                         # 只放壳层与共享层（业务模块在仓库根级）
│       ├── main.tsx                 # ReactDOM entry → <App />
│       ├── app/                     # App.tsx · AppShell.tsx · WorkspaceModuleTabs.tsx · hooks/
│       ├── shared/                  # lib/module-registry.ts · shell-context · http-client ·
│       │                            # realtime · handoff-api · use-handoff-contracts · 契约类型
│       ├── components/              # shadcn/ui 共享组件、error-boundary、startup-gate
│       └── standalone/shell-less.tsx# 独立构建共用的无 Shell 桩 Provider
│
├── ExecutionView/                   # 订单/路由工作台 [GA]（仓库根级，与 frontend/ 平级）
│   ├── module/                      # views/ · components/ · services/ · stores/(Zustand)
│   │                                # types/ · module.registry.ts · module.contract.ts · data/
│   └── standalone/                  # 独立构建入口
├── CostView/module/                 # 盘后 TCA UI [Beta]（唯一规范入口）
├── MarketView/module/               # 盘前壳锚点 [Scaffold]
│
├── backend/                         # ★ Core backend [GA]
│   ├── docker-compose.yml           # Docker Compose（6 服务，见 §11.4）
│   ├── docker-compose.host.yml      # Host-network 模式（本地 Bloomberg 终端）
│   └── api/
│       ├── main.py                  # FastAPI 装配入口（默认 :3000）；可选路由经 _register_optional
│       ├── auth.py · db.py · service_provider.py · config.py
│       ├── routers/                 # 核心 10 路由 + costview.py（可选桥接，含 Runner 代理）
│       ├── services/                # bloomberg/ 拆分包 · compliance · route_engine · algo_scheduler 等
│       ├── repositories/ · models/ · schemas/ · migrations/
│       └── tests/                   # 45 个测试文件 / 295 个测试函数（含 boundaries/ 契约测试）
│
├── MarketView/                      # 盘前微服务 [Scaffold]（默认 :8001）
│   ├── main.py · config.py
│   ├── routers/marketview.py        # snapshot / intraday-features / handoff 端点
│   ├── module/ · standalone/
│   └── tests/                       # 1 个测试文件（三个端点）
│
├── CostView/                        # 盘后 TCA 微服务 [Beta]（默认 :8002）
│   ├── pyproject.toml               # pip package: emsxview-costview
│   ├── api/routers/                 # costview.py（TCA 查询/推荐/交接/评估）· monitoring.py
│   ├── src/                         # tca_query_service · tca_query_builder · tca_cache · tca_utils
│   │                                # monitoring/ · evaluation/（统计评估层）· __main__.py（CLI）
│   └── tests/                       # 10 个测试文件 / 305 个测试函数；golden/ 内附冻结快照
│
├── data_access/                     # ★ 只读数据访问层 [Beta]
│   ├── config.py                    # Config：${EMSXVIEW_DATA_DIR} + 10 个库键 + 表常量
│   ├── storage/                     # ConnectionManager（READ tier，sqlite mode=ro）
│   └── processing/ · common/
│
├── platform_data/                   # 跨模块共享适配层 [Beta，部分规划中]
│   ├── adapters/                    # handoff · redis_handoff · tca_bridge · market
│   ├── contracts/                   # handoff/execution/tca/market/intraday 契约 + protocols
│   └── config.py · config_bridge.py · regime_query.py · pyproject.toml
│
├── docs/                            # spec/ · api/ · ops/ · textbook/ · archive/
├── specs/                           # 在途特性计划 <feature-id>/（已完成者归档至 docs/archive/）
└── scripts/                         # start/stop/restart/check-status · ops/ · deploy/ · devtools/
                                     # diagnose/ · ci/ · cleanup/ · quality_gate/ · reports/ · hooks/
```

## 7. 关键开发约定

### 7.1 TypeScript / React 编码规范

- 优先使用 `const`，避免 `let`，禁止 `var`
- 使用箭头函数，除非需要 `this` 绑定
- 优先使用函数式编程范式（map/filter/reduce）
- 每个函数不超过 30 行，使用 early return 减少嵌套
- **所有注释使用中文**
- 使用 `interface` 定义对象类型，使用 `type` 定义联合类型和工具类型
- 为所有函数参数和返回值添加类型注解
- 前端使用 **shadcn/ui** 组件（Radix UI + Tailwind CSS）。新增 UI 组件遵循同一模式——使用 `npx shadcn@latest add <component>` 添加。

### 7.2 前端状态管理

- 全局应用状态使用 React Context（通过 `useShellContext()` 访问 ShellContext）
- 实时数据流（订单/路由）使用 Zustand store（`order-stream-store`、`route-stream-store`）
- 跨模块通信：`ModuleRegistry` 注册（`frontend/src/shared/lib/module-registry.ts`）+ `useHandoffContracts()` hook + `handoff-api.ts` 服务
- 模块注册顺序：`execution`（order 0，默认，WS `/ws/orders`）、`marketview`（order 10）、`costview`（order 20）

### 7.3 Broker ↔ Exchange 映射清单（★ 维护点）

- **唯一数据源**：`frontend/src/shared/lib/broker-exchange-mapping.ts`（导出 `EXCHANGE_FOR_BROKER` / `getBrokerExchangeMapping()` / `EXCHANGE_LIST`）
- **维护方式**：增删交易所或 broker 时**只改 shared 文件**；`ExecutionView/module/data/broker-exchange-mapping.ts` 仅为 re-export 兼容层
- **Report 专有市场**：仅需出现在 Report Exchanges、但不进入授权表的交易所（如 `C1` 沪港通、`HK` 香港），加入 `REPORT_ONLY_EXCHANGES` 常量（挂 `EXCHANGE_LIST`，不挂 `EXCHANGE_FOR_BROKER`）
- **禁止**：在 `ExecutionView/module/data/broker-exchange-mapping.ts` 内直接编辑映射（改此处不生效且会造成漂移）

### 7.4 后端约定

- 后端使用 Pydantic v2 模型定义 schema；所有 API 响应包在 `ApiResponse` 中。
- 数据库读写由 `RepositoryProvider` 统一控制，gate 为 `ENABLE_DB_PERSISTENCE` 标志。
- 管道配置为唯一数据源——禁止硬编码数据库路径、表名及运行时参数；EMSXView 一律从 `data_access/config.Config` 导入（数据管道已迁独立仓库 EMSXDataPipeline，本仓库为只读消费者）。
- 后端可选路由器绝不可破坏核心 ExecutionView——使用 `main.py` 中的 `_register_optional` 模式。
- TCA 路由层级指标从 `tca_route_summary` 预计算表读取，禁止在查询时实时聚合。
- Backend 禁止直接 deep import `CostView.src.*`；**禁止 import `DataPipeline.*`**；须经由 `platform_data` 桥接入口（如 `register_costview_bridge_dependencies()`）完成 DI 注册（模块边界 AP-01）。
- `platform_data` 中 `CostViewAnalyticsAdapter`、`CostViewDatabaseAdapter`、`ExecutionHistoryAdapter`、`DataPlatformIngestionAdapter`、`build_platform_data_access()` / `PlatformDataAccess` 为**规划中、尚未实现**——禁止按符号 import 使用（见 [ADR-0013](docs/spec/adr/0013-platform-data-adapter-current-state.md)）。

### 7.5 数据访问（只读）

- 入口：`data_access.config.Config` + `data_access.storage.ConnectionManager`（仅 READ tier；WRITE/admin 请求被拒绝）。
- 数据根解析优先级：`${EMSXVIEW_DATA_DIR}` 环境变量 > `Config.DEFAULT_DATA_DIR`。
- 库/表常量全部在 `data_access/config.py`；与他仓共享的数据契约由契约测试锁定。
- **永不写入**：数据更新维护由独立仓库 EMSXDataPipeline 独占（§5.3 ETL 触发链）。

## 8. 文件放置规范（★ 必须遵守）

- **禁止在仓库根目录随意创建文件**。创建任何新文件前，必须先确定其按功能归属的既有目录。
- 根目录仅保留既有约定文件：`AGENTS.md`、`README.md`、`QUICKSTART.md`、`.emsxview-root`、`.gitignore` 及既有模块目录/配置。
- 功能 → 目录映射：

  | 文件类别 | 归属目录 |
  |---|---|
  | 后端业务代码 | `backend/api/` 分层子目录（`routers/` `services/` `schemas/`） |
  | CostView / MarketView | `CostView/api/`、`CostView/src/`、`CostView/tests/`；`MarketView/` |
  | 只读数据访问层（本仓库） | `data_access/`（mode=ro 连接 + 库/表常量 + 读 repository；配置唯一来源 `data_access/config.py` 的 `Config`） |
  | 数据管道写入方（仓库外） | 独立仓库 EMSXDataPipeline（唯一写入方）——本仓库**禁止 import**，文档中**不写其磁盘路径**，需引用时用本仓库 `data_access/*` 路径 |
  | 跨模块适配器 | `platform_data/adapters/`、`platform_data/contracts/` |
  | 前端共享代码 | `frontend/src/shared/`（`hooks/` `lib/` `services/` `types/`） |
  | 前端模块代码 | 一律仓库根级：`ExecutionView/module/`、`CostView/module/`、`MarketView/module/`（与 `frontend/` 平级，各带 `standalone/` 独立构建入口）；`frontend/src/` 只放壳层与共享层 |
  | 前端共享 UI | `frontend/src/components/`、`frontend/src/components/ui/` |
  | 测试 | 各模块自身 `tests/`（Python）或 `__tests__/`（前端） |
  | 运维/诊断脚本 | `scripts/`（部署启动器归 `scripts/deploy/`） |
  | 规范文档 / 其他文档 | `docs/spec/` / `docs/` |
  | 特性计划与清单 | `specs/<feature-id>/` |
  | 临时调试代码 | 仓库根 `_tmp/`（`.gitignore` 已忽略） |
  | 运行产物（日志、导出、生成图片） | `.gitignore` 覆盖的目录或系统临时目录 |

- **判定原则**：优先复用相邻同类既有路径；无明确归属时先查阅 `docs/spec/project-structure.md` 或征询用户，**不得默认落到根目录**；临时与交付物严格分离，任务结束由创建方清理 `_tmp/`。
- 完整细则见 [`.codebuddy/rules/coding-style.md` → 文件放置规范](.codebuddy/rules/coding-style.md)。

## 9. 启动器与项目根路径（★ 必须遵守）

- 项目根定位**唯一信息源**是仓库根的 `.emsxview-root` marker 文件；新增/修改 `scripts/deploy/` 下启动脚本时**必须**用 `Find-EmsxviewRoot`（向上查找 marker），**禁止**硬编码「向上 N 层」
- 启动器算出项目根后**必须** `Assert-ProjectRootValid` 自检，错路径立即 throw，**禁止**进入 120s 超时黑盒
- VBS 启动器只做 thin wrapper（隐藏窗口 + 调起 PS1），**禁止**在 VBS 内做路径深度计算或业务逻辑
- 详见 [AP-16 启动器路径硬编码 + 跨宿主语义错位](docs/spec/anti-patterns.md#ap-16-启动器路径硬编码--跨宿主语义错位)

## 10. Git 多任务并行工作流（★ [ADR-0700](docs/spec/adr/0700-git-worktree-parallel-workflow.md)）

- **核心方案**：Git Worktree + 独立 Feature 分支 + 每日 rebase origin/main；完整 SOP 见 [`docs/spec/git-workflow.md`](docs/spec/git-workflow.md)
- **一任务一分支一目录**：每个任务在兄弟目录 `../EMSXView-wt-<task>` 检出独立分支，主工作树保持干净（停在 main）；规格化特性任务分支名必须与 `specs/<feature-id>/` 目录名一致
- **同步纪律**：每个活跃任务每天至少一次 `git rebase origin/main`；临时保存用 commit，**禁止跨 worktree 使用 stash**（stash 为仓库级共享，极易拿错）
- **数据零受损**：数据落外置数据根 `${EMSXVIEW_DATA_DIR}`（与代码树解耦）；EMSXView 为只读消费者（sqlite mode=ro），数据更新维护的唯一写入方是独立仓库 EMSXDataPipeline。
- **Agent 隔离**：一个 Agent 绑定一个 worktree，禁止跨 worktree 读写文件或操作其他任务正在使用的分支；功能代码禁止直接提交 main（PR + Squash merge）
- **等待与轮询**：凡需等待外部状态变化（PR checks / Actions run / 服务就绪），一律**每 5 秒**检查一次（如 `gh pr checks <编号> --watch --interval 5`），轮询只用只读命令，以退出码作门禁判定
- 并行任务启动前必须先读 `docs/spec/git-workflow.md` §6（端口偏移 / 数据目录 / 依赖安装）与 §7（AI Agent 专项规则）

## 11. Build & Run Commands

### 11.1 一键启动（Windows）

```batch
scripts\start-all.bat        :: 启动
scripts\check-status.bat     :: 健康检查
scripts\stop-all.bat         :: 停止
scripts\restart-all.bat      :: 重启（交互式服务管理器）
```

### 11.2 前端

```bash
cd <repo-root>                  # npm workspaces 根（frontend + ExecutionView 共用一份依赖树）
npm install                     # 依赖只需在仓库根安装一次

cd frontend
npm run dev                     # Dev server http://<host>:<FRONTEND_PORT>（VITE_API_URL 为空则 mock 模式）
npm run build                   # 生产构建 → frontend/dist/
npm run typecheck               # tsc -b
npm run lint                    # ESLint（frontend/ 壳层与共享层）
npm run lint:modules            # ESLint（根级三业务模块）
npm test                        # vitest run

# 独立模块构建（产物在 frontend/dist-modules/，与主应用 frontend/dist/ 分离）
npm run build:execution
npm run build:costview
npm run build:marketview
npm run build:all-modules
```

> 仓库根也提供同名委派脚本：`npm run dev|build|typecheck|test|lint`（等价于在 `frontend/` 执行）。

### 11.3 后端与微服务

```bash
# Core backend（默认 :<API_PORT>）
cd <repo-root>/backend/api
pip install -r requirements.txt
python main.py

# CostView（默认 :<COSTVIEW_PORT>，无 Bloomberg 依赖）
cd <repo-root>
pip install -e CostView
pip install -r CostView/api/requirements.txt
cd CostView/api && python main.py

# MarketView（默认 :<MARKETVIEW_PORT>，无 Bloomberg 依赖）
cd <repo-root>/MarketView
pip install -r requirements.txt
python main.py

# CostView 只读查询 CLI（盘后巡检 / CI）
python -m CostView.src --query summary --date 20260408
# 退出码：0 成功 / 2 数据源不可用 / 3 结果为空且指定 --fail-on-empty
```

### 11.4 Docker（生产）

```bash
cd <repo-root>/backend
docker compose up -d                                  # 全栈
docker compose -f docker-compose.host.yml up -d       # host-network（本地 Bloomberg 终端）
docker compose --profile monitoring up -d             # 追加 Prometheus + Grafana
```

Compose 服务（6 个）：`backend`、`postgres`、`frontend`（Nginx，SPA + 反代）、`redis`，以及 `monitoring` profile 下的 `prometheus`、`grafana`。Nginx 路由：`/api/*` 与 `/ws/*` → backend，`/*` → 前端静态文件。

### 11.5 端口与环境变量

| 服务 | 默认 | 覆盖 |
|------|------|------|
| Frontend (dev) | `http://<host>:5173` | `npm run dev -- --port <FRONTEND_PORT>` |
| Core Backend / Swagger | `<API_BASE_URL>` / `/docs` | `API_HOST`、`API_PORT` |
| MarketView | `http://<host>:8001/docs` | `MARKETVIEW_HOST`、`MARKETVIEW_PORT` |
| CostView | `http://<host>:8002/docs` | `COSTVIEW_HOST`、`COSTVIEW_PORT` |
| 健康检查 | `<API_BASE_URL>/api/health` | `API_PORT` |

后端（默认值权威来源 `backend/api/config.py`）：

| 名称 | 作用 | 默认值 |
|------|------|--------|
| `BLOOMBERG_HOST` / `BLOOMBERG_PORT` | Bloomberg SAPI 连接 | `localhost` / `8194` |
| `JWT_SECRET` | JWT 签名密钥 | 空（未设且未开 `BYPASS_AUTH` 时启动即报错） |
| `EMSXVIEW_OPTIONAL_MODULES` | 可选路由桥接清单（`*`/`all` 加载全部，置空禁用） | `costview:CostView` |
| `EMSXVIEW_HANDOFF_BACKEND` | handoff 后端（`memory` / `redis`） | `memory` |
| `EMSXVIEW_REDIS_URL` | Redis 连接串（handoff / 缓存） | `redis://localhost:6379/0` |
| `ENABLE_DB_PERSISTENCE` | PostgreSQL 订单/路由持久化开关（关闭时内存 fallback） | `false` |
| `ALLOWED_ORIGINS` | CORS 允许来源（逗号分隔） | `http://localhost:5173,http://localhost:80` |
| `EMSXVIEW_RUNNER_URL` | 数据管道 Runner 地址（代理目标） | `http://127.0.0.1:8100` |

前端（`frontend/.env`）：

| 名称 | 作用 | 默认值 |
|------|------|--------|
| `VITE_API_URL` | Backend 基址；**留空 = mock / 无后端模式** | 空 |

数据访问：

```bash
# 数据根解析优先级：${EMSXVIEW_DATA_DIR} > Config.DEFAULT_DATA_DIR
set EMSXVIEW_DATA_DIR=<data-dir>          # Windows cmd
$env:EMSXVIEW_DATA_DIR = "<data-dir>"     # PowerShell
export EMSXVIEW_DATA_DIR=<data-dir>       # Linux / macOS

python -c "from data_access import ConnectionManager, Config; print(Config.DATA_DIR)"
```

## 12. 验证与质量门禁

| 范围 | 命令 | 规模/说明 |
|------|------|-----------|
| 后端全量 | `cd backend/api && python -m pytest tests/ -q` | 45 个测试文件 / 295 个测试函数 |
| 后端边界 | `python -m pytest backend/api/tests/boundaries/ -q` | 跨模块 import、DB 路径等契约 |
| CostView | `python -m pytest CostView/tests/ -q` | 10 个测试文件 / 305 个测试函数（含 golden 指标锁定） |
| MarketView | `python -m pytest MarketView/tests/ -q` | 1 个测试文件 |
| 前端 | `npm run typecheck && npm run lint && npm run lint:modules && npm test` | 25 个测试文件 |
| 边界审计 | `python scripts/audit_cross_imports.py`、`audit_underscore_access.py`、`audit_db_paths.py`、`audit_doc_drift.py` | CI `boundary-protection` 硬阻断 |
| 质量门禁 | `python scripts/quality_gate.py [--report|--staged]` | AP 契约 + OE 过度工程；规则见 [docs/spec/quality-gate.md](docs/spec/quality-gate.md) |

CI（`.github/workflows/boundary.yml`，job `boundary-protection`）三组：**audit**（四个审计脚本）、**backend-tests**（boundaries + 后端全量 + CostView 全量）、**frontend-tests**（typecheck + lint + lint:modules + vitest），全部硬阻断。另有 `doc-drift-report.yml`（周报）与 `cleanup-report.yml`。

## 13. 数据层与降级路径

### 13.1 存储规模（实测 2026-10-20，数据根 `${EMSXVIEW_DATA_DIR}`）

| 数据库 | 大小 | 用途 |
|--------|------|------|
| `raw_bdib.db` | 101.80 GB | 原始 BDIB 分钟 bars |
| `raw_fills.db` | 7.15 GB | 原始成交 |
| `execution_history.db` | 6.54 GB | 执行历史（orders/routes/route_events） |
| `processed_fills.db` | 5.98 GB | 清洗后成交 |
| `regime.db` | 4.57 GB | Regime 分类 + 归因 |
| `fill_bdib.db` | 1.78 GB | 成交 + BDIB 整合（含 `tca_route_summary` 预计算表） |
| `ticker_registry.db` | 0.03 GB | Ticker 注册 |
| `fill_fetch_history.db` / `bdib_fetch_history.db` | <1 MB | 拉取审计 |
| `processed_raw_bdib.db` | 0 GB（已退役） | 仅保留空库文件，写入开关在管道侧 |
| **合计** | **约 127.8 GB** | 10 个库键定义见 `data_access/config.py` |

### 13.2 选型理由与已知瓶颈

- **选型**：SQLite（`mode=ro` URI + WAL + busy timeout 30s）。理由：单一写入方（EMSXDataPipeline 串行日更）+ 本仓库纯读负载，SQLite 免运维；TCA 路由级指标从 `tca_route_summary` 预计算表读取，把热路径压到单表索引查询。
- **已知瓶颈**：① SQLite 单写者模型——多写入方并发不适用；② `raw_bdib.db` 超 100 GB，全量扫描类查询（报告导出附录）耗时长，已有超时降级（§13.3）；③ 管道吞吐为串行（`MAX_PARALLEL_DATES/TICKERS=1`）；④ 无并发用户数上限控制。

### 13.3 降级路径

| 触发条件 | 降级行为 | 用户感知 |
|----------|----------|----------|
| `fill_bdib.db` 文件缺失 | TCA 查询/时序查询返回**空结果**（`tca_query_builder.py` 捕获 `FileNotFoundError`） | 空页/空时序 + WARNING 日志 |
| 分析库任一文件/表缺失 | 可用性探测降级为 `False`（`tca_query_service.py`） | API 返回空数据 + WARNING 日志 |
| 报告导出时 BDIB 健康扫描超时/异常 | 附录**跳过**，报告主体照常生成（`monitoring/bdib_health.py`，守护线程 + 超时控制） | 导出的 HTML 缺 BDIB 缺口附录 + WARNING |
| CostView 查询缓存 Redis 连接失败 | 降级为**直连查询**（`tca_cache.py` try/except） | 响应变慢，无数据差异 |
| Bloomberg 会话未连接 / DB 断开 | `GET /api/health` 返回 `success=false` + 组件状态串 | 健康检查响应 |
| `ENABLE_DB_PERSISTENCE=false` | RepositoryProvider 回退**内存存储** | 重启即失 |
| 数据管道 Runner 不可达 / 已在运行 | 代理返回失败 / `pipeline already running` | `ApiResponse.error` |

**精度损失声明**：上述降级均为「缺数据 → 空结果/缺附录」，**不存在静默的数值精度替换**；报告口径的固有缺口（非降级、属数据源硬缺口）见 [docs/report-tca-known-limitations.md](docs/report-tca-known-limitations.md)。

## 14. 已失效声明（勿再引用）

以下说法曾出现在旧文档中，现已不成立，**不得**写回文档或代码注释：

| 失效项 | 现状 |
|---|---|
| `EMSXVIEW_MERGE_MODULES` 环境变量 / 「所有模块合并进单进程」 | 无消费点；可选模块用 `EMSXVIEW_OPTIONAL_MODULES`，且仅 CostView 可桥接（MarketView 无桥接路径） |
| `VITE_USE_MOCK` | 无消费点；mock 行为由 `VITE_API_URL` 是否为空决定 |
| `CORS_ORIGINS` | 实际变量名是 `ALLOWED_ORIGINS` |
| `tca_fallback.py`（独立降级模块） | 已删除；职责由各查询层内置空结果降级取代 |
| `CostView/requirements.txt`、`CostView/frontend/` | 分别于 2026-09-15、2026-08-26 删除；依赖见 `CostView/pyproject.toml` + `CostView/api/requirements.txt` |
| `frontend/src/modules/<module>/` | 业务模块已迁至仓库根级 `<Module>/module/`（`frontend/src/` 只放壳层与共享层） |
| `plans/` 目录 | 已不存在；计划统一放 `specs/<feature-id>/`，完成即归档至 `docs/archive/YYYY-MM-DD/` |
| `DataPipeline/`（本仓内目录 / import） | 已迁独立仓库 EMSXDataPipeline，本仓库禁止 import |
| 「Redis handoff 后端未实现 TTL」 | 已修：三通道均设 7 天 TTL（与内存后端 `_HANDOFF_TTL` 对齐） |
| 「黄金样本回归需外部冻结快照」 | 已修：`CostView/tests/golden/snapshot/fill_bdib.db` 随基线入库，`EMSXVIEW_GOLDEN_DATA_DIR` 仅为可选覆盖 |
| 「CostView 13 个端点」/「`TCA_ORDER_AGG_ENABLED` 默认关闭」 | 现状为 14 个端点，`TCA_ORDER_AGG_ENABLED`、`TCA_EVAL_ENABLED` 默认开启（置 `0` 显式降级） |
| 「MarketView 无自身测试目录」 | `MarketView/tests/` 已存在（1 个测试文件，覆盖三个端点） |
| 「后端 9 个核心路由 / 约 180 个测试函数」 | 现状 10 个核心路由（含 `authorizations`）、295 个测试函数 |

## 15. 文档地图

| Document | Purpose |
|----------|---------|
| [README.md](README.md) | 人类读者首页（概览 / 成熟度 / 快速启动） |
| [QUICKSTART.md](QUICKSTART.md) | Windows 一键启动 |
| [docs/index.md](docs/index.md) | 文档导航与维护规则（§7 占位符约定） |
| [docs/api-contracts.md](docs/api-contracts.md) | 前后端 API 契约（端点总览、各 Router 详述、错误码规范） |
| [docs/schema-contract.md](docs/schema-contract.md) | 跨模块 TS↔Python 类型契约（Contract 1–4） |
| [docs/report-tca-known-limitations.md](docs/report-tca-known-limitations.md) | TCA 报告口径缺陷清单 |
| [docs/spec/project-structure.md](docs/spec/project-structure.md) | 权威架构参考 |
| [docs/spec/data-domain.md](docs/spec/data-domain.md) | 逻辑数据域设计 |
| [docs/spec/memory.md](docs/spec/memory.md) | 架构记忆与长期约束（ADR 索引） |
| [docs/spec/anti-patterns.md](docs/spec/anti-patterns.md) | 禁止模式清单（AP-01~） |
| [docs/spec/quality-gate.md](docs/spec/quality-gate.md) | 质量门禁（AP + OE 规则） |
| [docs/spec/git-workflow.md](docs/spec/git-workflow.md) | Git Worktree 并行工作流 SOP |
| [docs/spec/adr/](docs/spec/adr/) | ADR 0001–0021 + 0700 |
| [docs/dev-guide.md](docs/dev-guide.md) | 开发指南与验证约束 |
| [docs/ops/service-management.md](docs/ops/service-management.md) | 启停、健康检查、日志查看 |
| [backend/README.md](backend/README.md) | 后端生产部署指南 |
| [CostView/README.md](CostView/README.md) | CostView 模块细节（端点表） |
| [MarketView/README.md](MarketView/README.md) | MarketView 模块细节 |
| [scripts/README.md](scripts/README.md) | 自动化脚本参考 |
| [docs/EMSXDataPipeline-TECHNICAL_GUIDE.md](docs/EMSXDataPipeline-TECHNICAL_GUIDE.md) | 独立数据管道仓库技术说明同步副本（真相源在 EMSXDataPipeline 仓库） |
