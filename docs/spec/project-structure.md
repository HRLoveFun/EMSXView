# EMSXView Project Structure

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
| MarketView | Pre-trade analysis, market context, execution preparation | Shell anchor exists, domain capabilities still to be built（定级 Scaffold） |
| ExecutionView | Real-time order and route management via Bloomberg EMSX | GA（判据与证据见主 [README.md §0](../../README.md#0-模块成熟度分级契约定义)：真实交易数据持续入库 + 约 180 个后端测试函数 + 运维手册；无正式 SLA 文档） |
| CostView | Post-trade analytics, TCA, broker recommendations, reporting | Beta（只读消费者；数据管道已迁独立仓库 EMSXDataPipeline） |

---

## 2. Canonical Runtime Architecture

```text
Browser
  |
  v
frontend/ (canonical React shell)
  |- MarketView module anchor
  |- ExecutionView workspace
  `- CostView module
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

## 3. Canonical Repository Structure

```text
EMSXView/
├── README.md
├── QUICKSTART.md
├── relaunch_service.bat
├── frontend/                         # Canonical React frontend shell
│   ├── package.json
│   └── src/
│       ├── app/
│       │   ├── App.tsx               # Module registry side-effect imports
│       │   ├── AppShell.tsx          # Root layout orchestrator
│       │   └── ...
│       ├── modules/
│       │   ├── execution/            # Execution domain module
│       │   ├── marketview/           # MarketView module anchor
│       │   └── costview/             # CostView module
│       └── shared/                   # Cross-module shared layer
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
│       └── tests/                    # 20 个测试文件，约 180 个测试函数（含 boundaries/ 契约测试）
├── MarketView/
│   ├── main.py                       # FastAPI entry（无 Bloomberg 依赖）
│   ├── config.py
│   ├── routers/marketview.py         # snapshot / intraday-features / handoff 端点
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
│   ├── tests/                        # 7 个测试文件，213 个测试函数（含 golden 基线回归）
│   # 注：CostView/frontend/（legacy prototype UI）已于 2026-08-26 删除（ADR-0014，见 §6.1）
│   #     data.migrated.202609022339/（2026-09-02 迁移留证，约 145GB）已于 2026-09-16
│   #     确认数据根稳定后删除；.gitignore 的 CostView/data.migrated.*/ 规则保留
├── platform_data/
│   ├── __init__.py
│   ├── adapters/                      # Cross-module adapters (subpackage)
│   │   ├── __init__.py                # Backward-compat re-export entry point
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
│   ├── open-todos.md
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

- `modules/marketview/` — pre-trade shell anchor
- `modules/execution/` — Execution workspace；对外接口契约收敛于 `modules/execution/module.contract.ts`
  （`ExecutionModuleProps` → `ExecutionModuleContribution`），模块禁止反向 import `@app/*`，宿主能力经 `@shared/lib/shell-context`
- `modules/costview/` — active post-trade UI

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
- New production UI work should go to `frontend/src/modules/costview/`.

### 6.2 Empty placeholders

- `app/` and `config/` legacy placeholder directories have been **deleted**.

### 6.3 Archived documents

- `docs/archive/` stores historical summaries, one-off diagnosis reports, and completed phase checklists.
- Archived documents are kept for audit/reference value, but are not source-of-truth for the current architecture.

---

## 7. Current Alignment Gaps

1. `CostView/frontend/` legacy prototype has been removed from the repository (formerly archived under `docs/archive/`) — removed from active surfaces.
2. ExecutionView operational data and CostView analytical data now have a shared adapter entry; cross-module deep imports from ExecutionView to CostView have been eliminated.
3. MarketView has a shell anchor, but the actual pre-trade workflows and data contracts remain to be built. MarketView runs as a standalone service on `<MARKETVIEW_PORT>` (default 8001).
4. Legacy CostView DB classes (`raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`) have been **deleted** — fully migrated to the pipeline repository's `DataPipeline/storage/` repositories per `docs/spec/data-domain.md`; EMSXView 侧对应物是本仓库的 `data_access/storage/`。
5. `platform_data/adapters.py` has been split into `platform_data/adapters/` subpackage (with backward-compat re-exports in `__init__.py`).

---

## Summary

The current live architecture is not “three separate applications.” It is:

- one canonical frontend shell
- three business modules
- one logical data domain with explicit ownership boundaries
- incremental bridges from old surfaces to new ones

This document is the source of truth for repository shape until further structural refactors are completed.
