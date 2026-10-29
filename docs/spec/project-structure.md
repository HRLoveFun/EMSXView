# EMSXView Project Structure

> L2 | 权威：仓库结构、权威实现面、模块使命与边界、逻辑数据域、遗留面 | 不权威：批次进度（见 `specs/057-*/tasks.md`）、成熟度证据（见 `README.md` §0）、编码约定（见 `docs/dev-guide.md`）

> Current architecture reference for the EMSXView Trading Platform
> Last updated: 2026-09-11 | Version: 3.4（对齐 [data-domain.md](data-domain.md) v3.4：刷新 CostView/src 实际文件、contracts 实际契约、成熟度定级引用；移除已迁移/已删除路径）

---

## Table of Contents

1. Project overview
2. Canonical runtime architecture
3. Canonical repository structure
4. Active implementation surfaces
5. Logical data domain
6. Legacy and prototype surfaces
7. Current alignment gaps
8. Module descriptions（能力清单）
9. 前端入口唯一表
10. Technology Stack

---

## 1. Project Overview

The repository is converging on this target shape:

- one canonical frontend shell
- three business modules: MarketView, ExecutionView, CostView
- one logical data domain with explicit subdomains and adapters

This is an incremental evolution of the live codebase, not a big-bang rewrite.

### Business modules

| Module | Role | Current implementation state |
|---|---|---|
| MarketView | Market trend view: stock-pool check, intent / execution-difficulty / expected-cost hints, read-only and never touches the order path | Beta（8 端点；池内量价/难度/成本同屏见 057 DL-29；SLA/运维文档未实现） |
| ExecutionView | Execution view: intent intake, order/route send & amend, execution-interval price/volume monitoring | GA（判据与证据见主 [README.md §0](../../README.md#0-模块成熟度分级契约定义)：真实交易数据持续入库 + 后端测试全绿（`cd backend/api && python -m pytest tests/ -q`）+ 运维手册；无正式 SLA 文档；执行区间量价视图见 057 DL-30） |
| CostView | Post-trade analytics, TCA, broker recommendations, reporting | Beta（只读消费者；数据管道已迁独立仓库 EMSXDataPipeline） |

### Module mission and boundaries（单一来源）

三个模块构成「交易前研判 → 交易中执行 → 交易后评估」的闭环；共享同一批行情、基线与成交数据，但**观察轴不同**，因此都保留、不能互相替代：

| 模块 | 使命 | 回答的问题 | 观察轴 | 不做什么 |
|------|------|------------|--------|----------|
| **MarketView** | 检查、更新股票池；监测股票池内标的 | 今天该关注哪些票、这些票的意图是什么、执行难度多大、成本大概多少 | 标的 × 交易日（交易前 · 市场走势） | **不碰下单路径**：不发送、不修改、不撤销订单/路由，不写任何库；股票池只做只读汇集，不做页面内编辑与持久化 |
| **ExecutionView** | 获取交易意图；发送、修改订单/路由；监测订单执行区间的量价变化 | 这笔（这批）委托正在做得怎么样、与市场和预期偏离多少 | 订单/路由 × 执行区间（交易中 · 交易执行） | 不承担选股与盘前研判；盘前结论只从 MarketView 交接读取；不重复实现行情/基线取数 |
| **CostView** | 盘后评估执行表现与成本，形成券商/算法评价并回流建议 | 成本贵在哪、花了多少、同类条件下哪家券商或算法更好 | 成交/路由 × 交易日（交易后 · 成本归因） | 不写库、不触发 ETL、不直连 Bloomberg；预期成本不对券商输出、不作为对外预测（K3） |

- **功能落点**：MarketView = 固定筛选池汇集与检查（量价指标与执行难度、预期成本同屏）+ 日度基线与事件状态 + 意图覆盖率与未匹配 + 池内盘中走势；ExecutionView = 意图交接读取 + 订单/路由发送与修改 + 合规与授权校验 + 实时订单流 + **以执行区间为窗口**的量价曲线与对照（取数复用 MarketView 的 bar / 基线路径）；CostView = TCA 分析与 scorecard（读 `tca_route_summary` 预计算表）+ 订单内配对与综合评估报告 + 监控与 HTML 报告导出 + 只读巡检 CLI + 券商推荐 pin（经 handoff 回流 ExecutionView）。
- **边界判定**：改动落在「标的/池/盘前提示」一侧归 MarketView；落在「订单/路由/执行区间」一侧归 ExecutionView；落在「成本归因/评分/评估口径」一侧归 CostView。跨侧只经 handoff 契约（`docs/schema-contract.md`）传递，禁止直接 import 对方模块。
- **顺序依赖**：MarketView 的结论是 ExecutionView 的输入；ExecutionView 的成交与决策记录是 CostView 的输入；CostView 的评价经 handoff 回流 ExecutionView，不反向改写前两者的过程数据。

---

## 2. Canonical Runtime Architecture

```text
Browser
  |
  v
frontend/ (canonical React shell: app/ 编排 + shared/ 契约层 + components/ 共享 UI)
  |
  +--ExecutionView/module   (交易执行视图：意图 / 下单改单 / 执行区间量价，仓库根级)
  +--CostView/module        (盘后分析 / TCA UI，仓库根级)
  `--MarketView/module      (市场走势视图：股票池 / 意图 / 难度与成本，仓库根级，只读)
  |
  v
backend/api (FastAPI assembly layer)
  |- routers/
  |- services/
  |- repositories/
  |- schemas/
  `- db.py / service_provider.py
  |
  +--> Bloomberg EMSX API (operational execution data)
  `--> CostView/src (analytical queries, read-only via data_access/)
```

Key runtime truth:

- `frontend/src/App.tsx` is the canonical UI entry point.
- `backend/api/main.py` is the application assembly entry point, not the sole location of business logic.
- `CostView/src/` is the active analytics implementation（只读；管道实现已迁独立仓库 EMSXDataPipeline）.
- `platform_data/` is the shared adapter entry for the logical data domain.

---

### Module flow（交易生命周期）

```text
MarketView (Market Trend) ──▶ ExecutionView (Order Execution) ──▶ CostView (Post-Trade TCA)
   [Beta]                          [GA]                              [Beta]
        │                             │                                │
  Stock Pools & Intent          Order/Route Send & Amend          TCA Analysis
  Difficulty & Expected Cost    Interval Price/Volume            Scorecard / Monitoring
  Handoff → Execution           Real-time WebSocket               Recommendations (pin)
```

## 3. Canonical Repository Structure

```text
EMSXView/
├── README.md
├── QUICKSTART.md
├── emsxview.bat                      # 服务管理统一入口（start/stop/restart/status）
├── relaunch_service.bat              # 双击重启（等待前端 + 打开页面）
├── package.json                      # npm workspaces 根（frontend + ExecutionView；lockfile 唯一在仓库根，ADR-0020）
├── frontend/                         # Canonical React frontend shell（壳层 + 共享层，不含业务模块）
│   ├── package.json
│   ├── dist/                         # 主应用构建产物（npm run build）
│   ├── dist-modules/                 # 独立模块构建产物（npm run build:<module>，与 dist/ 分离互不覆盖）
│   └── src/
│       ├── app/
│       │   ├── App.tsx               # Module registry side-effect imports
│       │   ├── AppShell.tsx          # Root layout orchestrator
│       │   └── ...
│       ├── standalone/
│       │   └── shell-less.tsx        # 独立构建用的无 Shell 桩 Provider（三个模块共用）
│       ├── components/               # 共享 UI（shadcn）
│       └── shared/                   # Cross-module shared layer
├── ExecutionView/                    # ExecutionView 模块（根级独立目录；012-executionview-root-extract）
│   ├── README.md                     # 职责边界 / 接口契约 / 运行与构建
│   ├── package.json                  # 自带依赖声明（npm workspaces 成员，ADR-0020）
│   ├── module/                       # 模块实现（components/ hooks/ views/ services/ stores/ types/ lib/ data/）
│   │   ├── module.registry.ts        # 自注册描述符（shell 经 moduleRegistry 发现）
│   │   └── module.contract.ts        # ★ 对外接口契约（ExecutionModuleProps / ExecutionModuleContribution）
│   └── standalone/                   # 独立构建入口（index.html + main.tsx）
├── data_access/                      # 只读数据访问层（010-extract-pipeline 后本仓库唯一数据入口）
│   ├── config.py                     # Config：数据根 + 库/表常量（唯一真相源）
│   ├── storage/                      # connection(mode=ro) / market_store / repositories / schema
│   ├── processing/                   # 读侧处理工具
│   └── common/                       # exchange_tz 等读侧公共工具
├── backend/
│   └── api/
│       ├── main.py                   # FastAPI application entry (<API_PORT>, default 3000)
│       ├── config.py
│       ├── deps.py
│       ├── db.py
│       ├── service_provider.py
│       ├── routers/
│       ├── services/
│       ├── repositories/
│       ├── models/
│       ├── schemas/                  # Pydantic v2 请求/响应 schema（目录，非单文件）
│       └── tests/                    # 含 boundaries/ 契约测试（规模跑命令看）
├── MarketView/
│   ├── main.py                       # FastAPI entry（无 Bloomberg 依赖）
│   ├── config.py
│   ├── routers/marketview.py         # snapshot / intraday-features / handoff 端点
│   ├── module/                       # 前端模块（仓库根级；原 frontend/src/modules/marketview/，018 平移）
│   ├── standalone/                   # 独立构建入口（index.html + main.tsx）
│   └── README.md
├── CostView/
│   ├── README.md
│   ├── pyproject.toml                # pip package: emsxview-costview（含 pandas 等运行时依赖声明）
│   ├── api/
│   │   ├── main.py                   # FastAPI entry (<COSTVIEW_PORT>, default 8002)
│   │   └── routers/
│   │       ├── costview.py           # analyze / analyze-orders / scorecard / recommendations pin / handoff peek / regime
│   │       └── monitoring.py         # bdib-health / metric-coverage / report-summary / anomaly-thresholds / export-html
│   ├── src/
│   │   ├── tca_query_service.py
│   │   ├── tca_query_builder.py
│   │   ├── tca_cache.py
│   │   ├── tca_utils.py
│   │   ├── __main__.py               # CLI 入口：python -m CostView.src（退出码 0/2/3）
│   │   ├── query_cli.py              # QueryEngine 类（CLI 命令分发目标）
│   │   └── monitoring/               # bdib_health · metric_coverage · report_aggregator · report_dims ·
│   │                                 #   anomaly_query · tca_report_html · time_range
│   ├── scripts/                      # golden 基线生成（gen_golden.py / make_golden_snapshot.py）
│   ├── tests/                        # 含 golden 基线回归（规模跑命令看）
│   ├── module/                       # 前端模块（仓库根级；原 frontend/src/modules/costview/，018 平移）
│   ├── standalone/                   # 独立构建入口（index.html + main.tsx）
│   # 注：CostView/frontend/（legacy prototype UI）已于 2026-08-26 删除（ADR-0014，见 §6.1）
│   #     data.migrated.202609022339/（2026-09-02 迁移留证，约 145GB）已于 2026-09-16
│   #     确认数据根稳定后删除；.gitignore 的 CostView/data.migrated.*/ 规则保留
├── platform_data/
│   ├── __init__.py
│   ├── adapters/                      # Cross-module adapters (subpackage)
│   │   ├── __init__.py                # 适配器 re-export 入口（2026-09-16 收敛：仅适配器与工厂）
│   │   ├── handoff.py                 # HandoffExchangeAdapter（内存交换器：TTL 7 天 + 容量上限）
│   │   ├── redis_handoff.py           # RedisHandoffExchangeAdapter
│   │   ├── market.py                  # MarketReferenceDataAdapter
│   │   └── tca_bridge.py              # TCA service DI + daily summary reader
│   └── contracts/                      # Cross-module data contracts（实际文件，2026-09-11 核实）
│       ├── __init__.py
│       ├── handoff_contracts.py
│       ├── execution_contracts.py
│       ├── tca_contracts.py            # SCORECARD_COHORTS + TCA 类型（原 fill_contracts.py 内容并入此处）
│       ├── market_contracts.py
│       ├── intraday_contracts.py
│       ├── data_access.py
│       ├── db_constants.py
│       ├── protocols.py
│       ├── tca_service_protocol.py
│       └── boundary_registry.py
├── docs/
│   ├── index.md
│   ├── api-contracts.md
│   ├── schema-contract.md
│   ├── dev-guide.md
│   ├── handoff-costview-html-report.md
│   ├── report-tca-known-limitations.md
│   ├── spec/
│   │   ├── project-structure.md
│   │   ├── data-domain.md
│   │   ├── module-api-contracts.md
│   │   └── memory.md
│   ├── ops/
│   └── archive/
├── scripts/
├── data/
└── logs/
```

---

## 4. Active Implementation Surfaces

### 4.1 Frontend shell

Canonical entry:

- `frontend/src/App.tsx`

Responsibilities:

- owns the platform shell
- mounts MarketView, ExecutionView, and CostView module surfaces
- remains the only authoritative browser entry point

Current module split inside the shell:

- `../ExecutionView/module/` — Execution view：意图获取、订单/路由发送与修改、执行区间量价（仓库根级，与 `frontend/` 平级）
- `../CostView/module/` — active post-trade UI（仓库根级）
- `../MarketView/module/` — Market trend view：股票池检查、意图/难度/成本提示（仓库根级，只读、不碰下单路径）

  （三模块对外接口契约与依赖约束：Execution workspace 的见下：
  对外接口契约收敛于 `ExecutionView/module/module.contract.ts`
  （`ExecutionModuleProps` → `ExecutionModuleContribution`），模块禁止反向 import `@app/*`，宿主能力经 `@shared/lib/shell-context`

> `modules/databaseview/` 已随 010-extract-pipeline 移除（数据库维护归独立仓库 EMSXDataPipeline 的 Runner）。

### 4.2 Backend assembly layer

Canonical entry:

- `backend/api/main.py`

Responsibilities:

- application startup and lifecycle
- router registration
- singleton wiring
- database bootstrap
- Bloomberg connectivity bootstrap

Active backend layering:

- `routers/` — HTTP and WebSocket surfaces by domain
- `services/` — business workflows and Bloomberg adapter logic
- `repositories/` — operational persistence access
- `models/` / `schemas/` — persistence and API contracts
- `db.py` / `service_provider.py` — operational data access boundary

### 4.3 CostView analytical layer

Canonical entries:

- `CostView/src/tca_query_service.py`
- [`data_access/storage/`](../../data_access/storage/) — read-only DB entry (`ConnectionManager` READ tier)

Responsibilities:

- cross-database TCA queries
- analytical metric assembly and reporting

Read-only data access layer ([`data_access/`](../../data_access/)):

- `config.py` — `Config`：数据根（环境变量 `EMSXVIEW_DATA_DIR` > 默认值）+ 库/表常量，唯一真相源
- `storage/connection.py` — `ConnectionManager`，仅提供 READ tier（sqlite3 `mode=ro`），WRITE/admin 一律拒绝
- `storage/market_store.py` — `MarketStoreReader`
- `storage/repositories/` — `SqliteFillReadRepository`、`SqliteRawFillReadRepository`
- `storage/schema/` — 列常量
- `processing/` / `common/` — 读侧处理与时区工具

写入侧（ETL 与数据维护）已迁独立仓库 EMSXDataPipeline；本仓库为只读消费者，禁止 `import DataPipeline.*`。
Legacy DB classes (`raw_fills_db.py` etc.) have been **deleted** — migrated to `DataPipeline/storage/` repositories in the pipeline repository.

### 4.4 Shared logical data-domain entry

Canonical entries:

- `platform_data/adapters/`
- `platform_data/contracts/`
- `platform_data/config_bridge.py`（配置桥接；原 `platform_data/repositories.py` 已随 DatabaseView 移除）

Responsibilities:

- exposes a stable adapter layer for platform code
- preserves ownership boundaries between Execution operational data and CostView analytical data
- avoids direct cross-domain deep imports becoming the default integration pattern
- `contracts/` defines the only legal cross-module data types (e.g. `SCORECARD_COHORTS`)
- `adapters/tca_bridge.py` 的 `get_tca_query_service()` 提供 TCA / scorecard 查询（读取 `tca_route_summary` 汇总表）
- 执行历史读取由 `CostView/src/tca_query_builder.py` 直接 SQL 提供（原平行实现 `execution_history_service.py` 已于 2026-08-26 移除，见 ADR-0014）
- DatabaseView 诊断查询入口（`platform_data/repositories.py`）已随 010-extract-pipeline 移除
- `CostViewDatabaseAdapter` / `CostViewAnalyticsAdapter` 尚未实现（规划中，见 `docs/spec/adr/0013-platform-data-adapter-current-state.md`）

---

## 5. Logical Data Domain

The repository does not yet use a single physical data store, and that is intentional.

The current data strategy is:

- one logical data domain
- multiple storage technologies chosen by workload
- adapter-based integration rather than storage collapse

### 5.1 Execution operational data

Owner:

- Execution backend

Workload:

- current order and route state
- warm-start projections
- audit events
- operational persistence with in-memory fallback

Current entry points:

- `backend/api/db.py`
- `backend/api/service_provider.py`
- `platform_data.adapters.HandoffExchangeAdapter` / `get_shared_handoff_exchange()` — 跨模块交接

Current storage model:

- PostgreSQL when enabled and healthy
- in-memory fallback when DB persistence is unavailable

### 5.2 CostView analytical data

Owner:

- CostView

Workload:

- raw fills
- processed fills
- raw BDIB market data
- integrated fill/market metrics
- TCA reports and derived analytics

Current entry points:

- `CostView/src/tca_query_service.py`（读取 `tca_route_summary` 汇总表）
- `platform_data.adapters.get_tca_query_service()` — 跨模块 TCA 查询工厂
- `build_platform_data_access()` 尚未实现（规划中）

Current storage model:

- SQLite analytical stores optimized for staged processing and re-computation

### 5.3 Integration rule

Cross-domain access should follow this order of preference:

1. use `platform_data/` adapters
2. use a documented domain service boundary
3. only as a temporary bridge, use direct deep imports with explicit justification

---

## 6. Legacy and Prototype Surfaces

### 6.1 Legacy frontend prototype

- `CostView/frontend/` prototype was first archived under `docs/archive/`, then **fully removed from the repository** in the 2026-08-26 dead-weight cleanup (recoverable from git history).
- It is not the canonical CostView UI.
- New production UI work should go to `CostView/module/`（仓库根级模块，与 `frontend/` 平级；2026-09-16 由 `frontend/src/modules/costview/` 平移，见 docs/archive/2026-09-21/018-costview-marketview-root-extract）。

### 6.2 Empty placeholders

- `app/` and `config/` legacy placeholder directories have been **deleted**.

### 6.3 Archived documents

- `docs/archive/` stores historical summaries, one-off diagnosis reports, and completed phase checklists.
- Archived documents are kept for audit/reference value, but are not source-of-truth for the current architecture.

---

## 7. Current Alignment Gaps

1. `CostView/frontend/` legacy prototype has been removed from the repository (formerly archived under `docs/archive/`) — removed from active surfaces.
2. ExecutionView operational data and CostView analytical data now have a shared adapter entry; cross-module deep imports from ExecutionView to CostView have been eliminated.
3. MarketView has delivered 7 endpoints and is graded Beta, but its stock pools are still the 4 fixed filter pools; pool-level intent/difficulty/cost aggregation and the ExecutionView execution-interval price/volume view remain to be built (057 DL-29 / DL-30). MarketView runs as a standalone service on `<MARKETVIEW_PORT>` (default 8001) and never touches the order path.
4. Legacy CostView DB classes (`raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`) have been **deleted** — fully migrated to the pipeline repository's `DataPipeline/storage/` repositories per `docs/spec/data-domain.md`; EMSXView 侧对应物是本仓库的 `data_access/storage/`。
5. `platform_data/adapters.py` has been split into `platform_data/adapters/` subpackage (with backward-compat re-exports in `__init__.py`).

---

## 8. Module Descriptions（能力清单）

每个模块给出：定位 / 入口 / 能力（**已实现 与 规划中 二分**，每条带入口+验证）/ 不做什么。模块深入细节见各子 README（§10）。

### 8.1 ExecutionView（`backend/api/` + `ExecutionView/module/`）— GA

**定位**：交易执行视图——获取交易意图，发送与修改订单/路由，并监测**订单执行区间**的量价变化（复用 MarketView 数据，以订单/路由生命周期为观察轴）。**入口**：`backend/api/main.py`（`<API_PORT>`，默认 3000）；核心路由 11 个始终加载（connection / authorizations / auth / orders / routes / broker / debug / realtime / market_broker_mapping / route_plans / interval_series），可选路由经 `_register_optional`。

**已实现能力**（能力 → 入口 → 验证）：

| 能力 | 入口 | 验证 |
|------|------|------|
| 订单 CRUD + 父子执行调度 | `routers/orders.py`（聚合 orders_crud/execution/handoff） | `tests/test_parent_child_execution.py` |
| 路由管理与批量操作 | `routers/routes.py`、`services/batch_route_service.py` | `tests/test_batch_route_endpoints.py` |
| 授权与合规（动作级鉴权、USD 名义额、odd lots） | `routers/authorizations.py`、`services/authorization_service.py`、`services/compliance_service.py` | `tests/test_compliance_service.py`、`tests/boundaries/` |
| WebSocket 实时推送（订单/路由流） | `routers/realtime.py`、`services/realtime_gateway.py` | `tests/test_realtime_gateway.py`；前端 `services/__tests__/realtime.test.ts` |
| JWT 认证 | `auth.py`、`routers/auth.py` | `tests/test_auth_policy.py` |
| 算法调度 | `services/algo_scheduler.py` | `tests/test_algo_scheduler.py` |
| Bloomberg EMSX 集成（订阅缓存、行情增强） | `services/bloomberg/`（adapter/connection/subscriptions/enrichment/request_handler） | `tests/test_bloomberg_adapter_routing.py` + `tests/test_bloomberg_adapter_refdata.py` |
| 基准计算 | `services/benchmark_engine.py` | `tests/test_benchmark_engine.py` |
| 健康检查 | `GET /api/health`（`routers/connection.py`，检查 Bloomberg + DB 状态） | 启动后 `curl <API_BASE_URL>/api/health` |
| 交易意图交接消费（MarketView → Execution，**现状仅徽标展示**） | `useHandoffContracts()` + `frontend/src/shared/services/handoff-api.ts` | 前端 handoff 相关测试 |
| 执行区间量价视图（DL-30：区间价格 / 累计量 / 区间 VWAP vs 成交均价 vs 到达价） | `GET /api/execution/interval-series`（`backend/api/routers/interval_series.py`）；MonitorBoard 点击 ticker 打开 `IntervalSeriesPanel` | `test_interval_series.py`、`interval-series-panel.test.tsx`、`interval-series.test.ts` |

**不做什么**：不承担选股与盘前研判（盘前结论以 MarketView 为准，本模块只读取其 handoff 候选，不重复计算）；不写分析库（分析库由 EMSXDataPipeline 独占写入）；订单/路由持久化仅经 `ENABLE_DB_PERSISTENCE` 门控写入 PostgreSQL（未启用时内存 fallback）；不承担 TCA 计算（读取方是 CostView）。

### 8.2 CostView（`CostView/`）— Beta

**定位**：盘后 TCA 分析与券商推荐（只读消费者）。**入口**：`CostView/api/main.py`（`<COSTVIEW_PORT>`，默认 8002）；可选经 backend `_register_optional` 桥接进 core 进程。前端入口见 §6。

**已实现能力**（能力 → 入口 → 验证）：

| 能力 | 入口 | 验证 |
|------|------|------|
| TCA 分析查询（route 级，读 `tca_route_summary` 预计算表） | `POST /api/tca/analyze`（`CostView/api/routers/costview.py`） | `tests/test_tca_query_service.py` |
| TCA 订单聚合查询（`TCA_ORDER_AGG_ENABLED` 默认开启，置 `0` 显式降级） | `POST /api/tca/analyze-orders` | `tests/test_order_aggregation.py` |
| 券商/策略 cohort scorecard | `POST /api/tca/scorecard` | `tests/test_tca_query_service.py` |
| 算法执行质量综合评估（分层比较 / 趋势 / 风险 / 可信度披露，`TCA_EVAL_ENABLED` 默认开启） | `POST /api/tca/evaluation/report` | `tests/`（评估层 `src/evaluation/`） |
| 券商推荐 pin（写入 handoff 供 ExecutionView 读取） | `POST /api/tca/recommendations/pin` | ExecutionView 侧 `GET /api/broker-recommendations` 消费 |
| Post-trade handoff 查看 | `GET /api/tca/handoff/post-trade/{order_id}` | 契约见 docs/schema-contract.md Contract 3 |
| Regime 分布查询 | `GET /api/costview/regime-distribution` | 运行时验证 |
| TCA 数据新鲜度 | `GET /api/tca/data-freshness` | `tests/test_data_freshness.py` |
| 可见能力清单（区间 / 维度 / 指标） | `GET /api/tca/capabilities` | `tests/test_cli_entrypoint.py` 间接覆盖入口一致性 |
| BDIB 健康扫描 / 指标覆盖率 / 报告聚合 / 异常阈值 | `GET /api/tca/monitoring/{bdib-health,metric-coverage,report-summary,anomaly-thresholds}`（`monitoring.py`） | `tests/test_monitoring.py` |
| 自包含 HTML 报告导出（含降级逻辑，见 §8） | `GET /api/tca/monitoring/export-html` | `tests/test_monitoring.py` + `tests/test_report_metrics.py` |
| 查询缓存（Redis，连接失败自动降级直查） | `src/tca_cache.py` | 降级行为见 §8 |
| 只读查询 CLI（盘后巡检 / CI） | `python -m CostView.src --query <fills\|raw-fills\|log\|order-log\|orders\|tickers\|summary>`（`src/__main__.py`） | `tests/test_cli_entrypoint.py` |

**已知欠缺 / 规划中**：
- **黄金样本回归**：基线 `CostView/tests/golden/*.json` 由 `CostView/scripts/gen_golden.py` 生成，冻结快照 `tests/golden/snapshot/fill_bdib.db` 随基线入库（CI 自包含）；`EMSXVIEW_GOLDEN_DATA_DIR` 可用于指向其他同源快照。缺基线时整组自动 skip。
- **覆盖率统计**：`CostView/pyproject.toml` 已配置 pytest + coverage，但**未设 `--cov-fail-under` 门槛**，故覆盖率仍属"未量化"。

**不做什么（职责边界）**：
- **不触发 ETL**：数据更新唯一写入方是独立仓库 EMSXDataPipeline；触发链路见 §3.2。
- **不写任何数据库**：全部经 `data_access` 只读连接（`mode=ro`）。
- **不直连 Bloomberg**：无 blpapi 依赖。
- **报告口径有已知硬缺口**（无数据源、报告应明示而非伪装完整）：见 [docs/report-tca-known-limitations.md §一](../report-tca-known-limitations.md#一硬缺口当前无数据源报告应明示而非伪装完整)。

### 8.3 MarketView（`MarketView/`）— Beta

**定位**：市场走势视图——检查、更新股票池，监测股票池内标的，把「今天该关注哪些票、这些票的意图是什么、执行难度多大、成本大概多少」算清楚。**只读数据、只做提示，不碰下单路径**（不发送/修改/撤销订单与路由，不写任何库）。

**入口**：`MarketView/main.py`（`<MARKETVIEW_PORT>`，默认 8001，无 Bloomberg 依赖）。

**已实现能力**：

| 能力 | 入口 | 验证 |
|------|------|------|
| 股票池检查与筛选（4 个固定池：all / volatility-watch / liquidity-watch / active-names） | `GET /api/marketview/snapshot`（`routers/marketview.py`） | `test_marketview_router.py` |
| 市场快照（收盘价、波动率、成交量、ADV） | `GET /api/marketview/snapshot`（`routers/marketview.py`） | `test_marketview_router.py` |
| 盘中特征（交易所本地时段分桶） | `GET /api/marketview/intraday-features` | 同上 |
| 意图获取与覆盖率（EMSX 导出 / 盘中库 `order_intent`） | `GET /api/marketview/pre-trade-orders`（`routers/export_orders.py`） | `test_export_orders.py`、`test_export_parser.py` |
| 盘前单四路装配（意图 + 基线 + 状态 + 预期成本） | `GET /api/marketview/pretrade-board`（`routers/pretrade.py`） | `test_pretrade_board.py`、`test_pretrade_board_intraday.py` |
| 日度基线（60 日稳健分布 → 执行难度输入） | `routers/baseline.py` | `test_baseline_router.py` |
| 事件与市场状态 | `routers/regime.py` | `test_regime_router.py` |
| Handoff 发布（Market → Execution，提示性候选） | `POST /api/marketview/handoff/execution` | `test_marketview_router.py` |
| 池内量价/难度/成本同屏（DL-29：仅现有 4 个固定筛选池） | `GET /api/marketview/pool-board`（`MarketView/routers/pool_board.py`）；前端 `PoolBoardPanel`（含实时 Bid/Ask/Last，经 `POST /api/market-state/subscribe` 订阅池内标的） | `test_pool_board.py`、`pool-board-panel.test.tsx`、`test_market_state_subscribe.py` |

**不做什么（职责边界）**：
- **不碰下单路径**：不发送、不修改、不撤销订单/路由；handoff 只发布提示性候选，是否下单由 ExecutionView 决定。
- **不写库**：全部经只读连接（`mode=ro`）；股票池更新为只读汇集，不做页面内持久化编辑。
- **不承担 TCA 归因**：盘后成本评估归 CostView；本模块只给盘前预期成本提示。

**已知限制**（Beta 定级依据）：见 [docs/milestone-1-pretrade-board.md §5](../milestone-1-pretrade-board.md)；池内量价/难度/成本同屏已实现（DL-29，待用户复核）；SLA/运维文档未实现；实时列默认开启（设 `EMSXVIEW_INTRADAY_STATE_ENABLED=false` 回退）。

### 8.4 frontend/（React 壳）— Beta

- **Technology:** React 19.2, TypeScript 5.9, Vite 7, Tailwind CSS 3.4, shadcn/ui, Recharts 2.15
- **Architecture:** Module Registry 模式——各模块经 `moduleRegistry.register()` 自注册（id / label / order / lazy component），壳动态发现，不硬编码模块路径（`frontend/src/shared/lib/module-registry.ts`）。
- **模块注册**：`execution`（order 0，默认，WS `/ws/orders`）、`marketview`（order 10）、`costview`（order 20）。
- **验证**：`npm test`（vitest）；`npm run lint`（壳层/共享层）+ `npm run lint:modules`（三业务模块）—— 两者自 2026-09-16 起均为 CI 硬阻断。

### 8.5 data_access/（只读数据访问层）— Beta

- **Entry Point:** `data_access.config.Config` + `data_access.ConnectionManager`（仅 READ tier；WRITE/admin 请求被拒绝）。
- **配置唯一来源**：数据根解析优先级 `${EMSXVIEW_DATA_DIR}` 环境变量 > `Config.DEFAULT_DATA_DIR`；库/表常量全部在 `data_access/config.py`，与他仓共享的数据契约由契约测试锁定。
- **验证**：`python -c "from data_access import ConnectionManager, Config; print(Config.DATA_DIR)"`。
- **不做什么**：永不写入；禁止其余模块硬编码库路径/表名。

### 8.6 platform_data/（跨模块共享适配层）— Beta（部分规划中）

- **已实现**：`HandoffAdapter`（内存/Redis 交换器，§3.1）、`TcaBridge`（TCA 服务注册路由）、`MarketReferenceDataAdapter`、契约文件、`ConnectionManagerProtocol`/`ConfigProtocol`。
- **规划中（未实现，禁止按符号 import）**：`CostViewAnalyticsAdapter`、`CostViewDatabaseAdapter`、`ExecutionHistoryAdapter`、`DataPlatformIngestionAdapter`、`build_platform_data_access()`——现状与恢复计划见 [ADR-0013](adr/0013-platform-data-adapter-current-state.md)。

---


## 9. 前端入口唯一表

| 入口 | 说明 | 状态 |
|------|------|------|
| `<Module>/module/`（仓库根级，主壳 tab；`ExecutionView` / `CostView` / `MarketView`） | 规范 UI 入口，三模块同壳 | **唯一规范入口** |
| `npm run build:execution` / `build:costview` / `build:marketview`（`vite.base.ts --module=<id>` → `frontend/dist-modules/<module>/`） | 独立 SPA 构建，**与主壳同源代码**，仅打包目标不同；产物与主应用 `frontend/dist/` 分离（ADR-0020） | 规范 |
| `<Module>/standalone/`（各模块自带入口）、`frontend/src/standalone/shell-less.tsx`（共用无 Shell 桩 Provider） | 独立构建所需的入口与壳适配层 | 规范 |
| ~~`CostView/frontend/`~~ | legacy prototype UI | **已于 2026-08-26 删除**（[ADR-0014](adr/0014-dead-code-cleanup.md)），勿再引用 |

---


## 10. Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend Shell** | React 19.2, TypeScript 5.9, Vite 7.x |
| **UI Framework** | Tailwind CSS 3.4, shadcn/ui (Radix UI primitives) |
| **Visualization** | Recharts 2.15 |
| **State Management** | React Context + Zustand（stream stores） |
| **Backend** | Python 3.11, FastAPI, Pydantic v2 |
| **Bloomberg API** | blpapi 3.19+, xbbg 0.7+ |
| **ORM** | SQLAlchemy 2.x |
| **Authentication** | JWT (PyJWT, passlib) |
| **Real-time** | WebSocket (FastAPI + browser native) |
| **Data Processing** | pandas, numpy, scipy |
| **Operational DB** | PostgreSQL（可选，订单/路由持久化，gate `ENABLE_DB_PERSISTENCE`） |
| **Analytical DB** | SQLite（`${EMSXVIEW_DATA_DIR}` 下 10 库，实测合计约 127.8 GB，见 §5.1） |
| **Cache & Messaging** | Redis 7（可选：handoff 微服务模式 + CostView 查询缓存） |
| **Reverse Proxy** | Nginx 1.27 |
| **Monitoring** | Prometheus + Grafana（optional `monitoring` profile） |
| **Containerization** | Docker Compose（6 服务） |

### Python Package Dependencies

```
emsxview-platform-data   ← pydantic, python-dateutil
emsxview-costview        ← pydantic, pandas, scipy, emsxview-platform-data
```

> CostView 的运行依赖统一由 `CostView/pyproject.toml` 声明；`data_access/` 是仓库内模块（非独立 pip 包）；原 `emsxview-datapipeline` 包已随 010-extract-pipeline 迁出至独立仓库 EMSXDataPipeline。

---


## Summary

The current live architecture is not “three separate applications.” It is:

- one canonical frontend shell
- three business modules
- one logical data domain with explicit ownership boundaries
- incremental bridges from old surfaces to new ones

This document is the source of truth for repository shape until further structural refactors are completed.
