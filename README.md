# EMSXView 交易平台

> 订单执行与交易成本分析（TCA）单体仓库：执行管理（ExecutionView）、盘前市场视图（MarketView）、盘后 TCA（CostView），共享一个 React 前端壳与一个只读数据访问层。

---

> **占位符约定**：`<host>` 默认 `localhost`；`<API_BASE_URL>` / `<MARKETVIEW_BASE_URL>` / `<COSTVIEW_BASE_URL>` 为可配置基址，默认 `http://localhost:3000` / `:8001` / `:8002`；`<repo-root>` 指仓库根（由 `.emsxview-root` marker 定位）；`${EMSXVIEW_DATA_DIR}` 指数据根。完整约定见 [docs/index.md §7](./docs/index.md#7-占位符与可配置参数约定)。

> **本 README 的可验证性原则**：本文件中每一项能力描述均标注"入口（文件/端点）+ 验证方式（测试/命令）"。标注「实测」的数据来自 2026-09-11 的静态代码审计与本机数据目录测量，未含运行时验证；过期的描述请在变更时同步更新 §变更摘要。

---

## 0. 模块成熟度分级（契约定义）

本仓库所有模块使用以下统一分级，**禁止**在无证据的情况下宣称"production-ready"等无判定标准的形容词：

| 等级 | 含义 | 必须满足的证据 |
|------|------|----------------|
| **GA / 生产就绪** | 已在真实交易流程中使用 | 真实交易数据持续入库 + 自动化测试覆盖核心路径 + 运维手册存在 |
| **Beta** | 功能完整但未全量 | 单元/集成测试 + 已知限制清单（known limitations）公开发布 |
| **Scaffold / 骨架** | 仅有接口与占位 | README 明确列出"未实现"清单 |

### 当前分级总表

| 模块 | 等级 | 判定证据 | 已知欠缺 |
|------|------|----------|----------|
| **ExecutionView**（`backend/api/` + `frontend/src/modules/execution/`） | **GA** | 真实成交数据持续入库（`raw_fills.db` 7.3 GB、`execution_history.db` 6.3 GB，实测 2026-09-11）；后端约 180 个测试函数覆盖订单/路由/合规/调度；运维手册 [docs/ops/service-management.md](./docs/ops/service-management.md) | 无正式 SLA 文档；无独立端到端集成测试套件（依赖 mock Bloomberg） |
| **CostView**（`CostView/` + `frontend/src/modules/costview/`） | **Beta** | 103 个测试函数（`CostView/tests/`，4 个文件）；已知限制清单 [docs/report-tca-known-limitations.md](./docs/report-tca-known-limitations.md)；11 个 API 端点全部可追溯到代码 | CLI 入口失效（`CostView/src/__main__.py` 缺失，见 §4.2）；测试覆盖率未量化；无黄金样本回归 |
| **MarketView**（`MarketView/`） | **Scaffold** | 仅 3 个端点（快照 / 盘中特征 / handoff 发布），无自身测试目录 | 见 §4.3 未实现清单 |
| **frontend/**（React 壳） | **Beta** | 17 个前端测试文件（vitest）；三模块注册完整 | 覆盖率未量化 |
| **data_access/**（只读数据层） | **Beta** | 契约测试锁定两仓常量一致（`data_access/config.py` 模块 docstring）；`mode=ro` 连接层 | 无自身测试目录 |
| **platform_data/**（跨模块适配层） | **Beta（部分规划中）** | handoff/contracts/tests 均有实现 | 部分 Adapter 为规划中、尚未实现，见 [ADR-0013](./docs/spec/adr/0013-platform-data-adapter-current-state.md)，禁止按符号 import |

---

## 1. Architecture Overview

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
│  │                      Shared Infrastructure                           │   │
│  │  frontend/ [Beta] (React shell) · platform_data/ [Beta] (adapters)   │   │
│  │  data_access/ [Beta] (read-only) · SQLite (只读, ~114GB) ·            │   │
│  │  PostgreSQL (可选) · Redis (可选) · Nginx                              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┄┄┄ 仓库外（独立仓库 EMSXDataPipeline）┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄   │
│  数据管道 Runner（唯一写入方，本机 :8100）──写入──▶ ${EMSXVIEW_DATA_DIR}      │
└──────────────────────────────────────────────────────────────────────────────┘
```

> 图中方框均携带成熟度标签（定义见 §0）。注意架构层级差异：MarketView 与 CostView 的能力完成度不对等，箭头仅表示数据流向，**不表示能力对等**。

### Module Flow (Trade Lifecycle)

```
MarketView (Pre-Trade) ──▶ ExecutionView (Order Execution) ──▶ CostView (Post-Trade TCA)
   [Scaffold]                   [GA]                              [Beta]
        │                          │                                │
  Market Snapshot            Orders & Routes                   TCA Analysis
  Intraday Features          Bloomberg EMSX API                Scorecard / Monitoring
  Handoff → Execution        Real-time WebSocket               Recommendations (pin)
```

### Deployment Modes

| Mode | 控制方式 | Architecture |
|------|----------|--------------|
| **Microservice**（默认） | 无需配置 | Core `<API_PORT>`、CostView `<COSTVIEW_PORT>` 独立进程 |
| **CostView 路由桥接**（可选） | `EMSXVIEW_OPTIONAL_MODULES`（默认 `costview:CostView`） | CostView 的 `/api/tca/*` 路由挂载进 core 进程（`backend/api/routers/costview.py`），前端经 `:3000` 单入口访问，无需启动 `:8002` |

> ⚠ 旧文档中的 `EMSXVIEW_MERGE_MODULES` 环境变量**已失效**（`backend/api` 无消费点，2026-09-11 核实）；"所有模块合并进单进程"的描述过时——MarketView **没有**桥接路径，仅独立运行（`backend/api/routers/` 无 marketview router）。可选模块经 `EMSXVIEW_OPTIONAL_MODULES` 配置（`*`/`all` 加载全部，当前已知模块仅 `costview`，见 `backend/api/main.py:276`）。

Cross-module handoff configurable via `EMSXVIEW_HANDOFF_BACKEND`:
- `memory` (default): 进程内 dict + `threading.Lock`（单进程/开发模式）
- `redis`: Redis 共享交换器（微服务/生产模式跨进程）

---

## 2. Directory Structure

```
EMSXView/
├── README.md                         # This file
├── QUICKSTART.md                     # One-command quick start guide
├── CODEBUDDY.md                      # Agent guidance for code assistants
├── relaunch_service.bat              # One-click restart
│
├── frontend/                         # ★ 规范 React 前端壳 [Beta]
│   ├── package.json                  # npm: emsxview-trading-tool
│   ├── vite.config.ts                # 主 Vite 配置（dev server <FRONTEND_PORT>, default 5173）
│   │   # 另有 vite.config.{execution,costview,marketview}.ts 三个独立 SPA 构建配置
│   └── src/
│       ├── main.tsx                  # ReactDOM entry → <App />
│       ├── app/                      # App.tsx · AppShell.tsx · WorkspaceModuleTabs.tsx · Toolbar.tsx
│       ├── modules/
│       │   ├── execution/            # 订单/路由工作台 [GA]
│       │   │   ├── views/            # OrderTable, RouteTable, ExecutionBoard, MonitorBoard, BatchOperationPanel
│       │   │   ├── components/       # 24+ dialogs (cancel, modify, batch-route, algo-launch, etc.)
│       │   │   ├── services/         # orders-api, routes-api, broker-api, realtime, etc.
│       │   │   ├── stores/           # order-stream-store, route-stream-store (Zustand)
│       │   │   └── types/
│       │   ├── costview/             # Post-trade TCA UI [Beta]（CostView 前端唯一规范入口）
│       │   │   ├── components/       # Overview, Scorecard, Analysis, FilterWorkbench, Charts, Export
│       │   │   └── services/         # TCA API client
│       │   └── marketview/           # Pre-trade shell anchor [Scaffold]
│       ├── shared/                   # ModuleRegistry, ShellContext, http-client, WS, handoff-api
│       ├── components/               # shadcn/ui shared components, error-boundary, startup-gate
│       └── standalone/               # Standalone SPA builds for each module
│
├── backend/                          # ★ Core backend [GA]
│   ├── docker-compose.yml            # Production Docker (8 services)
│   ├── docker-compose.host.yml       # Host-network mode for local Bloomberg
│   └── api/
│       ├── main.py                   # FastAPI entry (<API_PORT>, default 3000)；可选路由经 _register_optional
│       ├── auth.py                   # JWT auth manager
│       ├── db.py                     # SQLAlchemy engine & session
│       ├── service_provider.py       # RepositoryProvider（DB ↔ in-memory fallback，gate: ENABLE_DB_PERSISTENCE）
│       ├── routers/                  # 核心 9 路由 + costview.py（Runner 代理）等可选路由
│       ├── services/                 # 业务逻辑层（bloomberg/ 拆分包、compliance、route_engine、algo_scheduler 等）
│       ├── repositories/ · models/ · schemas/ · migrations/
│       └── tests/                    # 20 个测试文件，约 180 个测试函数（含 boundaries/ 契约测试）
│
├── MarketView/                       # Pre-trade microservice [Scaffold] (<MARKETVIEW_PORT>, default 8001)
│   ├── main.py                       # FastAPI entry (无 Bloomberg 依赖)
│   └── routers/marketview.py         # snapshot / intraday-features / handoff 端点
│
├── CostView/                         # Post-trade TCA microservice [Beta] (<COSTVIEW_PORT>, default 8002)
│   ├── pyproject.toml                # pip package: emsxview-costview
│   ├── api/
│   │   ├── main.py                   # FastAPI entry
│   │   └── routers/
│   │       ├── costview.py           # TCA analyze/analyze-orders/scorecard + recommendations pin + handoff peek + regime
│   │       └── monitoring.py         # bdib-health / metric-coverage / report-summary / anomaly-thresholds / export-html
│   ├── src/
│   │   ├── tca_query_service.py      # 核心 TCA 查询编排（读 tca_route_summary 预计算表）
│   │   ├── tca_query_builder.py      # SQL 查询构建器（库缺失 → 降级空结果）
│   │   ├── tca_cache.py              # 查询缓存（Redis，连接失败 → 降级直查）
│   │   ├── tca_utils.py              # 纯函数（日期/时间、cohort、scorecard）
│   │   ├── query_cli.py              # QueryEngine 类（⚠ __main__.py 缺失，CLI 命令行入口失效）
│   │   ├── secure_config.py          # 加密配置
│   │   └── monitoring/               # bdib_health · metric_coverage · report_aggregator · report_html 等
│   └── tests/                        # 4 个测试文件，103 个测试函数
│   # 注：CostView/frontend/（legacy prototype UI）已于 2026-08-26 清理（ADR-0014）；
#   #     CostView/data/ 历史数据已于 2026-09-02 迁移至 ${EMSXVIEW_DATA_DIR}
│
├── data_access/                      # ★ 只读数据访问层 [Beta]
│   ├── config.py                     # Config：${EMSXVIEW_DATA_DIR}（默认 D:\db）+ 10 个库键 + 表常量
│   ├── storage/                      # ConnectionManager（READ tier, sqlite mode=ro）、read repositories
│   ├── processing/ · common/
│   # 注：ETL 写入方（原 DataPipeline/）已迁独立仓库 EMSXDataPipeline；
│   #     本仓库为只读消费者，禁止 import DataPipeline.*
│
├── platform_data/                    # 跨模块共享适配层 [Beta，部分规划中]
│   ├── adapters/                     # handoff.py（内存交换器）· redis_handoff.py · tca_bridge.py · market.py
│   ├── contracts/                    # handoff/execution/tca/market/intraday 数据契约 + protocols.py
│   ├── config_bridge.py · regime_query.py
│   # 注：CostViewAnalyticsAdapter / CostViewDatabaseAdapter / ExecutionHistoryAdapter /
#   #     DataPlatformIngestionAdapter / build_platform_data_access() 为规划中未实现（ADR-0013）
│
├── docs/                             # 文档（引用锚点见 §10）
├── scripts/                          # start-all.bat · stop-all.bat · ops/ · deploy/ · devtools/ · diagnose/
├── plans/ · specs/ · data/ · logs/ · .github/
```

---

## 3. 跨模块数据流（方向 · 时序 · 一致性）

### 3.1 Handoff 交换器（`platform_data/adapters/`）

```
MarketView ──mv-to-ev──▶ ExecutionView ◀──cv-to-ev (recommendations)── CostView
                              │  ▲
                              └──ev-to-cv──▶ CostView (post-trade peek)
```

| 通道 | 方向 | 写入端点 | 读取端点 | 容量/时序语义 |
|------|------|----------|----------|----------------|
| Market → Execution | 单槽（仅保留最新一份） | `POST /api/marketview/handoff/execution`（`MarketView/routers/marketview.py:457`） | ExecutionView 经 handoff API 读取 | 新写入覆盖旧值；无历史 |
| Execution → Cost | 按 order_id 映射 | ExecutionView 成交后写入 | `GET /api/tca/handoff/post-trade/{order_id}`（`CostView/api/routers/costview.py:408`） | 上限 500 条，TTL 7 天惰性清理，超限淘汰最旧 |
| Cost → Execution（recommendations） | 追加列表 | `POST /api/tca/recommendations/pin`（`CostView/api/routers/costview.py:362`） | `GET /api/broker-recommendations`（`backend/api/routers/broker.py`） | 上限 200 条，追加 + 截断，**last-write-wins** |

**时序与一致性保证（重要）**：
- **同步性**：写入是请求内同步操作；读取是消费方在自身请求内**同步拉取**（无推送订阅）。前端经 `useHandoffContracts()` hook + `frontend/src/shared/services/handoff-api.ts` 按需读取。
- **可能读到过期数据**：内存后端条目 TTL 7 天，TTL 内的旧 recommendation 不会被自动失效——ExecutionView 读到的是"最近一次 pin 的结论"，不保证反映 CostView 最新分析。
- **冲突解决**：无合并逻辑，一律 last-write-wins；并发 pin 以后到达者为准。
- **无跨模块事务**：handoff 写入与业务写库是两个独立操作，无原子性保证。
- **Redis 后端差异**：3 个 key（`mv-to-ev` / `ev-to-cv` / `cv-to-ev`），`cv-to-ev` 列表上限 200（`rpush`+`ltrim`）；**Redis 后端未实现 TTL 过期**（过期语义仅内存后端具备），条目需人工关注新鲜度。
- **载荷限制**：strategy_params ≤ 64 KB（`platform_data/adapters/handoff.py:34`）。

契约定义：[docs/schema-contract.md](./docs/schema-contract.md)（Contract 1–4，含 MarketView→ExecutionView、ExecutionView→CostView、CostView→ExecutionView recommendation 的完整字段）。

### 3.2 ETL 触发链（跨仓库，CostView 是只读消费者）

```
前端/脚本 ──POST /api/tca/runner/run (JWT 鉴权)──▶ backend :3000 ──代理──▶ EMSXDataPipeline Runner :8100 POST /run
                  GET /api/tca/runner/status ──────────────────────────▶ GET /status
```

- **职责归属**：数据更新（ETL 写入）唯一写入方是独立仓库 EMSXDataPipeline；CostView 自身**没有任何写库路径**（`data_access` 全部 `mode=ro`）。
- **入口**：`backend/api/routers/costview.py:73` / `:88`（JWT 鉴权代理，前端统一经 `:3000`，不直连 Runner `:8100`）。
- **失败处理**：Runner 不可达 → `ApiResponse(success=False, "Runner unreachable: ...")`；Runner 返回非 2xx / 非 JSON → 失败响应。代理不会重试。
- **幂等性**：Runner 为**单任务模型**——已在运行时再次触发返回 HTTP 409，代理转而返回当前 `GET /status` 结果 + `"pipeline already running"`，不会并发重复执行。

---

## 4. Module Descriptions（最小完整描述）

每个模块给出：定位 / 入口 / 能力（**已实现 与 规划中 二分**，每条带入口+验证）/ 不做什么 / 验证命令。模块深入细节见各子 README（§10）。

### 4.1 ExecutionView（`backend/api/` + `frontend/src/modules/execution/`）— GA

**定位**：订单与路由执行管理核心服务，Bloomberg EMSX 集成。**入口**：`backend/api/main.py`（`<API_PORT>`，默认 3000）；核心路由 9 个始终加载（connection / auth / orders / routes / broker / realtime / debug / route_plans / market_broker_mapping），可选路由经 `_register_optional`（`main.py:314`）。

**已实现能力**（能力 → 入口 → 验证）：

| 能力 | 入口 | 验证 |
|------|------|------|
| 订单 CRUD + 父子执行调度 | `routers/orders.py`（聚合 orders_crud/execution/handoff） | `tests/test_parent_child_execution.py`（26 用例） |
| 路由管理与批量操作 | `routers/routes.py`、`services/batch_route_service.py` | `tests/test_batch_route_endpoints.py`（9） |
| WebSocket 实时推送（订单/路由流） | `routers/realtime.py`、`services/realtime_gateway.py` | `tests/test_realtime_gateway.py`（11）；前端 `services/__tests__/realtime.test.ts` |
| JWT 认证 | `auth.py`、`routers/auth.py` | `tests/test_auth_policy.py`（12） |
| 盘前合规检查（USD 名义额、odd lots） | `services/compliance_service.py` | `tests/test_compliance_service.py`（17） |
| 算法调度 | `services/algo_scheduler.py` | `tests/test_algo_scheduler.py`（28） |
| Bloomberg EMSX 集成（订阅缓存、行情增强） | `services/bloomberg/`（adapter/connection/subscriptions/enrichment/request_handler） | `tests/test_bloomberg_adapter_routing.py`（9）+ `test_bloomberg_adapter_refdata.py`（5） |
| 基准计算 | `services/benchmark_engine.py` | `tests/test_benchmark_engine.py`（26） |
| 健康检查 | `GET /api/health`（`routers/connection.py:36`，检查 Bloomberg + DB 状态） | 启动后 `curl <API_BASE_URL>/api/health` |

**不做什么**：不写分析库（分析库由 EMSXDataPipeline 独占写入）；订单/路由持久化仅经 `ENABLE_DB_PERSISTENCE` 门控写入 PostgreSQL（未启用时内存 fallback）；不承担 TCA 计算（读取方是 CostView）。

### 4.2 CostView（`CostView/`）— Beta

**定位**：盘后 TCA 分析与券商推荐（只读消费者）。**入口**：`CostView/api/main.py`（`<COSTVIEW_PORT>`，默认 8002）；单进程合并模式下经 backend `_register_optional` 加载。前端入口见 §6。

**已实现能力**（能力 → 入口 → 验证）：

| 能力 | 入口 | 验证 |
|------|------|------|
| TCA 分析查询（route 级，读 `tca_route_summary` 预计算表） | `POST /api/tca/analyze`（`CostView/api/routers/costview.py:174`） | `tests/test_tca_query_service.py`（27 用例） |
| TCA 订单聚合查询（`TCA_ORDER_AGG_ENABLED` 默认关闭） | `POST /api/tca/analyze-orders`（`costview.py:233`） | `tests/test_order_aggregation.py`（9） |
| 券商/策略 cohort scorecard | `POST /api/tca/scorecard`（`costview.py:289`） | `tests/test_tca_query_service.py` |
| 券商推荐 pin（写入 handoff 供 ExecutionView 读取） | `POST /api/tca/recommendations/pin`（`costview.py:362`） | ExecutionView 侧 `GET /api/broker-recommendations` 消费 |
| Post-trade handoff 查看 | `GET /api/tca/handoff/post-trade/{order_id}`（`costview.py:408`） | 契约见 docs/schema-contract.md Contract 3 |
| Regime 分布查询 | `GET /api/costview/regime-distribution`（`costview.py:470`） | 运行时验证 |
| BDIB 数据健康扫描 / 指标覆盖率 / 报告聚合 / 异常阈值 | `GET /api/tca/monitoring/{bdib-health,metric-coverage,report-summary,anomaly-thresholds}`（`monitoring.py`） | `tests/test_monitoring.py`（50 用例） |
| 自包含 HTML 报告导出（含降级逻辑，见 §8） | `GET /api/tca/monitoring/export-html`（`monitoring.py:270`） | `tests/test_monitoring.py` |
| 查询缓存（Redis，连接失败自动降级直查） | `src/tca_cache.py` | 降级行为见 §8 |

**规划中 / 入口失效**：
- **CLI 命令行入口失效**：`CostView/src/__main__.py` 不存在，旧文档中的 `python -m CostView.src --date ...` 命令**不可用**。`src/query_cli.py` 的 `QueryEngine` 类可编程调用，等待恢复 `__main__.py` 入口（调用方式见该文件 docstring）。
- **黄金样本回归测试**：未建立（无基准计算的快照对比测试）。
- **覆盖率统计**：未配置 coverage 工具链。

**不做什么（职责边界）**：
- **不触发 ETL**：数据更新唯一写入方是独立仓库 EMSXDataPipeline；触发链路见 §3.2。
- **不写任何数据库**：全部经 `data_access` 只读连接（`mode=ro`）。
- **不直连 Bloomberg**：无 blpapi 依赖。
- **报告口径有已知硬缺口**（无数据源、报告应明示而非伪装完整）：见 [docs/report-tca-known-limitations.md §一](./docs/report-tca-known-limitations.md#一硬缺口当前无数据源报告应明示而非伪装完整)。

### 4.3 MarketView（`MarketView/`）— Scaffold

**定位**：盘前市场数据视图骨架。**入口**：`MarketView/main.py`（`<MARKETVIEW_PORT>`，默认 8001，无 Bloomberg 依赖）。

**已实现能力**：

| 能力 | 入口 | 验证 |
|------|------|------|
| 市场快照 API（收盘价、波动率、成交量、ADV） | `GET /api/marketview/snapshot`（`routers/marketview.py:146`） | `backend/api/tests/test_marketview_router.py`（2 用例，合并模式挂载） |
| 盘中特征数据 | `GET /api/marketview/intraday-features`（`marketview.py:341`） | 同上 |
| Handoff 发布（Market → Execution） | `POST /api/marketview/handoff/execution`（`marketview.py:457`） | 同上 |

**未实现清单**（Scaffold 定级依据）：策略分析、选券支持、独立测试目录（`MarketView/` 无自身 tests/）、SLA/运维文档。

### 4.4 frontend/（React 壳）— Beta

- **Technology:** React 19.2, TypeScript 5.9, Vite 7.2, Tailwind CSS 3.4, shadcn/ui, Recharts 2.15
- **Architecture:** Module Registry 模式——各模块经 `moduleRegistry.register()` 自注册（id / label / order / lazy component），壳动态发现，不硬编码模块路径。
- **模块注册**：`execution`（order 0，默认，WS `/ws/orders`）、`marketview`（order 10）、`costview`（order 20）。
- **验证**：`npm test`（17 个测试文件）；`npm run lint`。

### 4.5 data_access/（只读数据访问层）— Beta

- **Entry Point:** `data_access.config.Config` + `data_access.ConnectionManager`（仅 READ tier；WRITE/admin 请求被拒绝）。
- **配置唯一来源**：数据根解析优先级 `${EMSXVIEW_DATA_DIR}` 环境变量 > 默认 `D:\db`（`Config.DEFAULT_DATA_DIR`）；库/表常量全部在 `data_access/config.py`，与他仓共享的数据契约由契约测试锁定。
- **验证**：`python -c "from data_access import ConnectionManager, Config; print(Config.DATA_DIR)"`。
- **不做什么**：永不写入；禁止其余模块硬编码库路径/表名。

### 4.6 platform_data/（跨模块共享适配层）— Beta（部分规划中）

- **已实现**：`HandoffAdapter`（内存/Redis 交换器，§3.1）、`TcaBridge`（TCA 服务注册路由）、`MarketReferenceDataAdapter`、7 个契约文件、`ConnectionManagerProtocol`/`ConfigProtocol`。
- **规划中（未实现，禁止按符号 import）**：`CostViewAnalyticsAdapter`、`CostViewDatabaseAdapter`、`ExecutionHistoryAdapter`、`DataPlatformIngestionAdapter`、`build_platform_data_access()`——现状与恢复计划见 [ADR-0013](./docs/spec/adr/0013-platform-data-adapter-current-state.md)。

---

## 5. 数据层（规模实测 · 选型理由 · 已知瓶颈）

### 5.1 数据存储规模（实测 2026-09-11，数据根 `${EMSXVIEW_DATA_DIR}`）

| 数据库 | 大小 | 用途 |
|--------|------|------|
| `raw_bdib.db` | 88.8 GB | 原始 BDIB 分钟 bars |
| `raw_fills.db` | 7.3 GB | 原始成交 |
| `execution_history.db` | 6.3 GB | 执行历史（orders/routes/route_events） |
| `processed_fills.db` | 5.7 GB | 清洗后成交 |
| `regime.db` | 4.7 GB | Regime 分类 + 归因 |
| `fill_bdib.db` | 1.6 GB | 成交+BDIB 整合（含 `tca_route_summary` 预计算表） |
| `ticker_registry.db` | 27 MB | Ticker 注册 |
| `fill_fetch_history.db` / `bdib_fetch_history.db` | <1 MB | 拉取审计 |
| `processed_raw_bdib.db` | 已退役（`PROCESSED_RAW_BDIB_ENABLED=0`，观察期通过 2026-06-15） | — |
| **合计** | **约 114 GB** | 10 个库键定义见 `data_access/config.py` |

### 5.2 选型理由与已知瓶颈

- **选型**：SQLite（`mode=ro` URI + WAL + busy timeout 30s，`Config.SQLITE_BUSY_TIMEOUT_MS=30_000`）。理由：单一写入方（EMSXDataPipeline 串行日更）+ 本仓库纯读的分析负载，SQLite 免运维、零部署成本；TCA 路由级指标从 `tca_route_summary` **预计算表**读取（查询时禁止实时聚合），将热路径压到单表索引查询。
- **已知瓶颈（如实标注）**：① SQLite 单写者模型——若未来多写入方并发则不适用；② `raw_bdib.db` 近 90 GB，全量扫描类查询（如报告导出的 BDIB 缺口附录）耗时长，已有超时降级保护（§8）；③ `MAX_PARALLEL_DATES/TICKERS=1`，管道吞吐为串行；④ 无并发用户数上限控制，多用户同时重查询未做排队。
- **写路径归属**：数据刷新/维护由独立仓库 EMSXDataPipeline Runner（`POST /run`、`GET /status`）执行；触发链见 §3.2。本仓库任何代码不得写入上述库。

---

## 6. 前端入口唯一表

| 入口 | 说明 | 状态 |
|------|------|------|
| `frontend/src/modules/<module>/`（主壳 tab） | 规范 UI 入口，三模块同壳 | **唯一规范入口** |
| `npm run build:execution` / `build:costview` / `build:marketview`（`vite.config.<module>.ts` → `dist/<module>/`） | 独立 SPA 构建，**与主壳同源代码**，仅打包目标不同 | 规范 |
| `frontend/src/standalone/` | 独立构建所需的壳适配层 | 规范 |
| ~~`CostView/frontend/`~~ | legacy prototype UI | **已于 2026-08-26 删除**（[ADR-0014](./docs/spec/adr/0014-dead-code-cleanup.md)），勿再引用 |

---

## 7. Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend Shell** | React 19.2, TypeScript 5.9, Vite 7.2 |
| **UI Framework** | Tailwind CSS 3.4, shadcn/ui (Radix UI primitives) |
| **Visualization** | Recharts 2.15 |
| **State Management** | React Context + Zustand（stream stores） |
| **Backend** | Python 3.11, FastAPI, Pydantic v2 |
| **Bloomberg API** | blpapi 3.19+, xbbg 0.7+ |
| **ORM** | SQLAlchemy 2.x |
| **Authentication** | JWT (PyJWT, passlib) |
| **Real-time** | WebSocket (FastAPI + browser native) |
| **Data Processing** | pandas, numpy |
| **Operational DB** | PostgreSQL（可选，订单/路由持久化，gate `ENABLE_DB_PERSISTENCE`） |
| **Analytical DB** | SQLite（`${EMSXVIEW_DATA_DIR}` 下 10 库，实测合计约 114 GB，见 §5.1） |
| **Cache & Messaging** | Redis 7（可选：handoff 微服务模式 + CostView 查询缓存） |
| **Reverse Proxy** | Nginx 1.27 |
| **Monitoring** | Prometheus + Grafana (optional profile) |
| **Containerization** | Docker Compose (8 services) |

### Python Package Dependencies

```
emsxview-platform-data   ← pydantic, python-dateutil
emsxview-costview        ← pydantic, emsxview-platform-data
```

> `data_access/` 是仓库内模块（非独立 pip 包）；原 `emsxview-datapipeline` 包已随 010-extract-pipeline 迁出至独立仓库 EMSXDataPipeline。

---

## 8. 降级路径（Degradation Paths）

主路径失败时的已知降级行为（均经代码核实）：

| 触发条件 | 降级行为 | 用户感知方式 |
|----------|----------|--------------|
| `fill_bdib.db` 文件缺失 | TCA 查询/时序查询返回**空结果**（`tca_query_builder.py:62,133` 捕获 `FileNotFoundError`） | 响应为空页/空时序 + WARNING 日志 |
| 分析库任一文件/表缺失 | 可用性探测降级为 `False`（`tca_query_service.py:86`） | API 返回空数据 + WARNING 日志 |
| 报告导出时 BDIB 健康扫描超时/异常 | 附录降级为**跳过**，报告主体照常生成（`monitoring/bdib_health.py:327-357`，守护线程 + 超时控制） | 导出的 HTML 缺 BDIB 缺口附录 + WARNING 日志 `BDIB 健康查询超时…导出附录降级跳过` |
| CostView 查询缓存 Redis 连接失败 | 降级为**直连查询**（`tca_cache.py` get/set 处 try/except） | 响应变慢，无数据差异 |
| Bloomberg 会话未连接 / DB 断开 | `GET /api/health` 返回 `success=false` + 组件状态串 | 健康检查响应 + `bloomberg=..., database=...` 消息 |
| `ENABLE_DB_PERSISTENCE=false` | RepositoryProvider 回退**内存存储**（重启即失） | 无持久化，重启数据丢失 |
| 数据管道 Runner 不可达 / 已在运行 | 代理返回失败 / `pipeline already running`（§3.2） | `ApiResponse.error` 字段 |

> 历史说明：`tca_fallback.py`（独立降级模块）**已删除**，其职责由上述各查询层内置的空结果降级取代；旧文档若仍引用该文件即为过时。

**精度损失声明**：上述降级均为"缺数据 → 空结果/缺附录"，**不存在静默的数值精度替换**；报告口径的固有缺口（非降级、属数据源硬缺口）见 [docs/report-tca-known-limitations.md](./docs/report-tca-known-limitations.md)。

---

## 9. Installation & Running

### Quick Start (Windows)

```bash
# One-command launch (see QUICKSTART.md for details)
scripts\start-all.bat

# Check service health
scripts\check-status.bat
```

### Ports & Hosts

Service URLs (`<host>` defaults to `localhost`):
| Service | URL | Default | Override env var |
|---------|-----|---------|------------------|
| Frontend (dev) | `http://<host>:<FRONTEND_PORT>` | `http://localhost:5173` | `npx vite --port <FRONTEND_PORT>` |
| Core Backend | `<API_BASE_URL>` | `http://localhost:3000` | `API_PORT` |
| API Docs (Swagger) | `<API_BASE_URL>/docs` | `http://localhost:3000/docs` | `API_PORT` |
| MarketView | `<MARKETVIEW_BASE_URL>/docs` | `http://localhost:8001/docs` | `MARKETVIEW_PORT` |
| CostView | `<COSTVIEW_BASE_URL>/docs` | `http://localhost:8002/docs` | `COSTVIEW_PORT` |
| Health Check | `<API_BASE_URL>/api/health` | `http://localhost:3000/api/health` | `API_PORT` |

### Prerequisites

- **Bloomberg Terminal** with API enabled (required for live execution；MarketView/CostView 无此依赖)
- **Node.js 20+** (for frontend development)
- **Python 3.11+** (for backend & CostView)
- **Docker Desktop 4.x** (for production deployment)

### Frontend Development

```bash
cd <repo-root>/frontend
npm install
npm run dev                     # Dev server on http://<host>:<FRONTEND_PORT> (default 5173)
                                # Mock mode if VITE_API_URL is empty

npm run build                   # Production build → dist/
npm run lint                    # ESLint
npm test                        # vitest run

# Standalone module builds
npm run build:execution         # → dist/execution/
npm run build:costview          # → dist/costview/
npm run build:all-modules       # 全部模块 SPA
```

Environment variables (`frontend/.env`):
- `VITE_API_URL=` — Backend URL (empty = mock/no backend), e.g. `http://<host>:<API_PORT>`
- `VITE_USE_MOCK=true` — Enable mock Bloomberg data

### Backend Development (Core)

```bash
cd <repo-root>/backend/api
pip install -r requirements.txt          # Includes -e ../../platform_data

# 可选：将 CostView 的 /api/tca/* 路由桥接进 core 进程（默认即启用）
set EMSXVIEW_OPTIONAL_MODULES=costview:CostView
python main.py                           # Starts on <API_PORT> (default 3000)

# Run tests（约 180 个测试函数）
pytest
```

Environment variables (`backend/.env`):
- `BLOOMBERG_HOST`, `BLOOMBERG_PORT` — Bloomberg SAPI connection
- `JWT_SECRET` — JWT signing key
- `EMSXVIEW_OPTIONAL_MODULES` — 可选路由桥接清单（默认 `costview:CostView`；`EMSXVIEW_MERGE_MODULES` 已失效）
- `EMSXVIEW_HANDOFF_BACKEND` — `memory` or `redis`
- `ENABLE_DB_PERSISTENCE` — Enable PostgreSQL order/route persistence
- `CORS_ORIGINS` — Frontend origin for CORS

### Microservice Backends

```bash
# MarketView standalone (<MARKETVIEW_PORT>, no Bloomberg)
cd <repo-root>/MarketView
pip install -r requirements.txt
python main.py

# CostView standalone (<COSTVIEW_PORT>, no Bloomberg)
cd <repo-root>
pip install -e CostView
cd CostView/api
pip install -r requirements.txt
python main.py
```

### Data Access (read-only)

EMSXView 通过 `data_access/` 只读消费分析库；写入由独立仓库 EMSXDataPipeline 执行。

```bash
# 数据根解析优先级：${EMSXVIEW_DATA_DIR} > data_access.config.Config.DEFAULT_DATA_DIR (默认 D:\db)
# Windows
set EMSXVIEW_DATA_DIR=<data-dir>
# Linux / macOS
export EMSXVIEW_DATA_DIR=<data-dir>

# 只读连接自检（READ tier；任何写请求会被拒绝）
python -c "from data_access import ConnectionManager, Config; print(Config.DATA_DIR)"

# Run CostView tests（103 个测试函数）
python -m pytest CostView/tests/

# ⚠ CLI 注意：`python -m CostView.src` 入口已失效（__main__.py 缺失，见 §4.2）；
#    编程调用方式见 CostView/src/query_cli.py 的 QueryEngine
```

### Docker (Production)

```bash
cd <repo-root>/backend

# Full stack: backend + postgres + frontend (Nginx) + redis
docker compose up -d

# With host-network (local Bloomberg Terminal)
docker compose -f docker-compose.host.yml up -d

# With monitoring (Prometheus + Grafana)
docker compose --profile monitoring up -d
```

Docker Compose services (compose 内端口可通过 `.env` 覆盖宿主映射；容器内端口由对应服务配置决定):
| Service | Container port | Host mapping | Purpose | Override env var |
|---------|----------------|--------------|---------|------------------|
| backend | `<API_PORT>` (3000) | 未默认映射（经 Nginx 反代） | FastAPI core | `API_PORT` |
| postgres | 5432 | `${POSTGRES_PORT:-5432}:5432` | Operational DB | `POSTGRES_PORT` |
| frontend (Nginx) | 80 | `${FRONTEND_PORT:-80}:80` | SPA + reverse proxy | `FRONTEND_PORT` |
| redis | 6379 | 未映射宿主端口（仅 compose 网络内） | Cache + handoff | — |
| prometheus (opt) | 9090 | `${PROMETHEUS_PORT:-9090}:9090` | Metrics collection | `PROMETHEUS_PORT` |
| grafana (opt) | 3000 | `${GRAFANA_PORT:-3001}:3000` | Dashboards | `GRAFANA_PORT` |

Nginx routes: `/api/*` → backend `<API_PORT>`, `/ws/*` → backend `<API_PORT>`, `/*` → frontend static files.

---

## 10. Related Documentation（引用均经存在性核对）

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | One-command Windows service launcher |
| [CODEBUDDY.md](./CODEBUDDY.md) | Agent guidance with build/test commands |
| [docs/index.md](./docs/index.md) | 文档导航（§7 占位符约定） |
| [docs/api-contracts.md](./docs/api-contracts.md) | 前后端 API 契约（§4 端点总览、§5.1–5.9 各 Router 详述、§8 错误码规范） |
| [docs/schema-contract.md](./docs/schema-contract.md) | 跨模块 TS↔Python 类型契约（Contract 1 HandoffMetadata、Contract 2 MV→EV、Contract 3 EV→CV、Contract 4 CV→EV recommendation） |
| [docs/report-tca-known-limitations.md](./docs/report-tca-known-limitations.md) | TCA 报告口径缺陷清单（§一 硬缺口 / §三 口径脚注） |
| [docs/spec/project-structure.md](./docs/spec/project-structure.md) | Canonical architecture reference |
| [docs/spec/data-domain.md](./docs/spec/data-domain.md) | Logical data domain design |
| [docs/spec/memory.md](./docs/spec/memory.md) | Architecture memory & constraints |
| [docs/spec/adr/](./docs/spec/adr/) | ADR 0001–0017 + 0700（0013 platform_data 现状 / 0014 dead-code cleanup） |
| [docs/dev-guide.md](./docs/dev-guide.md) | Developer guide |
| [docs/ops/service-management.md](./docs/ops/service-management.md) | Service operations & troubleshooting |
| [backend/README.md](./backend/README.md) | Backend production deployment guide |
| [CostView/README.md](./CostView/README.md) | CostView 模块细节（端点表） |
| [MarketView/README.md](./MarketView/README.md) | MarketView 模块细节 |
| [scripts/README.md](./scripts/README.md) | Automation scripts reference |

> 文档主从关系（原则：主 README 可独立回答"模块是什么"）：§4 已给出各模块最小完整描述；上述子文档仅作深入补充。

---

## 11. 变更摘要（模块级，可追溯记录）

| 日期 | 变更 | 影响模块 | 依据 |
|------|------|----------|------|
| 2026-08-26 | 清理一次性历史件与 legacy 前端（handoff/migration-baseline/architecture-analysis-report、`CostView/frontend/` legacy-costview-frontend 等） | CostView（前端入口收敛至 `frontend/src/modules/costview/`，见 §6）、docs | [ADR-0014](./docs/spec/adr/0014-dead-code-cleanup.md) |
| 2026-09-02 | `CostView/data/` 历史数据迁移至 `${EMSXVIEW_DATA_DIR}`（目录归档为 `CostView/data.migrated.202609022339/`） | CostView、data_access | 数据根唯一来源 `data_access/config.py` |
| 2026-09-11 | 本 README 全面审计重写：成熟度分级、能力"已实现/规划中"二分、数据流时序语义、数据规模实测、降级路径、CLI 失效标注；删除 `tca_fallback.py` 引用（文件已不存在）、删除 "production-ready"/"enterprise-grade"/"canonical" 无判据标注 | 全部模块 | 静态代码审计 + 数据目录实测（验证方式见页脚） |

---

**Last updated**: 2026-09-11
**Last verified**: 2026-09-11（验证人：AI 代码审计；验证方式：静态代码审计 + 端点清单提取 + `${EMSXVIEW_DATA_DIR}` 文件大小实测 + 测试函数计数。**未做运行时验证**——服务启动、端点实际响应与查询延迟未在本审计中测量。）
