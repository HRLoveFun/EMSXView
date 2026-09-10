# EMSXView Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis, order execution, and post-trade TCA analytics**

---

> **占位符约定**：`<host>` 默认 `localhost`；`<API_BASE_URL>` / `<MARKETVIEW_BASE_URL>` / `<COSTVIEW_BASE_URL>` 为可配置基址，默认 `http://localhost:3000` / `:8001` / `:8002`；`<repo-root>` 指仓库根（由 `.emsxview-root` marker 定位）；`${EMSXVIEW_DATA_DIR}` 指数据根。完整约定见 [docs/index.md §7](./docs/index.md#7-占位符与可配置参数约定)。

---

## Architecture Overview

EMSXView is a monorepo trading platform converging on **one canonical React frontend shell**, **three business modules**, and **one logical data domain** covering the full trade lifecycle:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         EMSXView Trading Platform                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐            │
│  │   MarketView    │──▶│  ExecutionView  │──▶│    CostView     │            │
│  │  (Pre-Trade)    │   │  (Order Exec)   │   │  (Post-Trade)   │            │
│  │ :<MARKETVIEW_PORT> │   │ :<API_PORT>     │   │ :<COSTVIEW_PORT> │           │
│  └────────┬────────┘   └───────┬─────────┘   └───────┬─────────┘            │
│           │                    │                     │                      │
│           ▼                    ▼                     ▼                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Shared Infrastructure                           │   │
│  │  frontend/ (React shell)  ·  platform_data/ (adapters & contracts)   │   │
│  │  data_access/ (read-only data layer) · PostgreSQL · Redis · Nginx    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

> 端口占位含义与默认值：`<API_PORT>` = 3000，`<MARKETVIEW_PORT>` = 8001，`<COSTVIEW_PORT>` = 8002，`<FRONTEND_PORT>` = 5173（开发态）。多任务并行时按 worktree 端口偏移覆盖，见 [docs/spec/git-workflow.md §6](./docs/spec/git-workflow.md)。

### Module Flow (Trade Lifecycle)

```
MarketView (Pre-Trade) ──▶ ExecutionView (Order Execution) ──▶ CostView (Post-Trade TCA)
        │                           │                                │
  Market Snapshot           Orders & Routes                   TCA Analysis
  Intraday Features         Bloomberg EMSX API               Performance Reports
  Handoff → Execution       Real-time WebSocket              Cost Attribution
                                                             Market Regime Detection
```

### Deployment Modes

| Mode | Env Var (`EMSXVIEW_MERGE_MODULES`) | Architecture |
|------|-----------------------------------|--------------|
| **Microservice** (production) | `false` (default) | Core `<API_PORT>`, MarketView `<MARKETVIEW_PORT>`, CostView `<COSTVIEW_PORT>` |
| **Single-process** (dev/demo) | `true` | All modules in one process on `<API_PORT>` |

Default ports: `<API_PORT>` = 3000, `<MARKETVIEW_PORT>` = 8001, `<COSTVIEW_PORT>` = 8002 — all overridable via env vars (see [§Ports & Hosts](#ports--hosts)).

Cross-module handoff configurable via `EMSXVIEW_HANDOFF_BACKEND`:
- `memory` (default): In-process dict + threading.Lock
- `redis`: Redis pub/sub for cross-process communication in microservice mode

---

## Directory Structure

```
EMSXView/
├── README.md                         # This file
├── QUICKSTART.md                     # One-command quick start guide
├── CODEBUDDY.md                      # Agent guidance for code assistants
├── relaunch_service.bat              # One-click restart
│
├── frontend/                         # ★ Canonical React frontend shell
│   ├── package.json                  # npm: emsxview-trading-tool
│   ├── vite.config.ts                # Main Vite config (dev server <FRONTEND_PORT>, default 5173)
│   ├── tailwind.config.js            # Tailwind CSS + shadcn/ui theme
│   ├── tsconfig.app.json             # Strict TypeScript config
│   ├── index.html                    # HTML entry point
│   └── src/
│       ├── main.tsx                  # ReactDOM entry → <App />
│       ├── app/
│       │   ├── App.tsx               # Module registry side-effect imports
│       │   ├── AppShell.tsx          # Root layout orchestrator (auth, WS, tabs, toasts)
│       │   ├── WorkspaceModuleTabs.tsx  # Module tab bar with handoff badges
│       │   ├── Toolbar.tsx           # Global toolbar
│       │   └── hooks/                # use-module-navigation, use-startup-status
│       ├── modules/
│       │   ├── execution/            # Order/Route management (production-ready)
│       │   │   ├── ExecutionModule.tsx
│       │   │   ├── views/            # OrderTable, RouteTable, ExecutionBoard, MonitorBoard, BatchOperationPanel
│       │   │   ├── components/       # 24+ dialogs (cancel, modify, batch-route, algo-launch, etc.)
│       │   │   ├── services/         # orders-api, routes-api, broker-api, realtime, etc.
│       │   │   ├── stores/           # order-stream-store, route-stream-store (Zustand)
│       │   │   └── types/            # order, route, batch, broker, compliance, etc.
│       │   ├── costview/             # Post-trade TCA UI (canonical)
│       │   │   ├── CostViewModule.tsx
│       │   │   ├── components/       # Overview, Scorecard, Analysis, FilterWorkbench, Charts, Export
│       │   │   ├── services/         # TCA API client
│       │   │   └── types.ts
│       │   └── marketview/           # Pre-trade shell anchor
│       │       ├── MarketViewModule.tsx
│       │       ├── intraday-feature-panel.tsx
│       │       └── services/
│       ├── shared/                   # Cross-module shared layer
│       │   ├── lib/                  # ModuleRegistry, ShellContext, utils
│       │   ├── services/             # http-client, realtime WS, handoff-api, startup-api, token-service
│       │   ├── hooks/                # use-handoff-contracts, use-mobile
│       │   └── types/
│       ├── components/               # shadcn/ui shared components (20+), error-boundary, startup-gate
│       └── standalone/               # Standalone SPA builds for each module
│
├── backend/                          # ★ Core backend service
│   ├── docker-compose.yml            # Production Docker (8 services)
│   ├── docker-compose.host.yml       # Host-network mode for local Bloomberg
│   ├── config/                       # Grafana dashboards, Nginx conf, Prometheus config
│   └── api/
│       ├── main.py                   # FastAPI application entry (<API_PORT>, default 3000)
│       ├── config.py                 # Settings (env → config)
│       ├── deps.py                   # Depends() dependency injection wiring
│       ├── auth.py                   # JWT auth manager
│       ├── db.py                     # SQLAlchemy engine & session
│       ├── service_provider.py       # RepositoryProvider (DB ↔ in-memory fallback)
│       ├── routers/                  # HTTP/WebSocket routers
│       │   ├── orders.py             # Aggregates orders_crud + orders_execution + orders_handoff
│       │   ├── routes.py             # Route CRUD operations
│       │   ├── broker.py             # Broker algorithm config
│       │   ├── connection.py         # Bloomberg connection status
│       │   ├── auth.py               # Authentication endpoints
│       │   ├── realtime.py           # WebSocket realtime push
│       │   ├── route_plans.py        # Route plan management
│       │   ├── market_broker_mapping.py  # Market-to-broker mapping
│       │   ├── costview.py           # CostView bridge API (optional)
│       │   └── debug.py              # Debug endpoints
│       ├── services/                 # Business logic layer
│       │   ├── bloomberg/            # Bloomberg EMSX service (split package)
│       │   │   ├── adapter.py        # Canonical facade
│       │   │   ├── connection.py     # Session lifecycle & status
│       │   │   ├── subscriptions.py  # Order/route cache & persistence
│       │   │   ├── enrichment.py     # Market data streaming, FX, round lot
│       │   │   └── request_handler.py # CRUD operations, broker/strategy queries
│       │   ├── auth_service.py       # JWT authentication
│       │   ├── compliance_service.py # Pre-trade compliance checks
│       │   ├── route_service.py      # Route business logic
│       │   ├── route_engine.py       # Route computation engine
│       │   ├── algo_scheduler.py     # Algorithm scheduling
│       │   ├── batch_route_service.py # Batch route operations
│       │   ├── benchmark_engine.py   # Benchmark calculations
│       │   ├── broker_storage_service.py  # Broker config persistence
│       │   ├── config_service.py     # Configuration management
│       │   ├── realtime_gateway.py   # WebSocket realtime gateway
│       │   ├── order_projections.py  # Order data projection
│       │   └── route_projections.py  # Route data projection
│       ├── repositories/             # Data access layer
│       ├── models/                   # SQLAlchemy persistence models
│       ├── schemas/                  # Pydantic v2 request/response schemas
│       └── migrations/               # DB migration scripts
│
├── MarketView/                       # Pre-trade microservice (<MARKETVIEW_PORT>, default 8001)
│   ├── main.py                       # FastAPI entry (no Bloomberg dependency)
│   ├── config.py
│   └── routers/
│       └── marketview.py             # Market snapshot & intraday features API
│
├── CostView/                         # Post-trade TCA microservice (<COSTVIEW_PORT>, default 8002)
│   ├── pyproject.toml                # pip package: emsxview-costview
│   ├── api/                          # Standalone FastAPI service
│   │   ├── main.py                   # FastAPI entry (no Bloomberg dependency)
│   │   └── routers/
│   │       └── costview.py           # TCA analyze, trigger-update, recommendations
│   ├── src/                          # Analytical engine & CLI
│   │   ├── __main__.py               # CLI: python -m CostView.src --date YYYY-MM-DD
│   │   ├── tca_query_service.py      # Core TCA query logic
│   │   ├── tca_query_builder.py      # TCA query builder
│   │   ├── tca_utils.py              # Shared TCA utilities
│   │   ├── query_cli.py              # CLI query interface
│   │   ├── tca_fallback.py           # Fallback TCA processing
│   │   └── secure_config.py          # Secure config handling
│   ├── tests/                        # Unit tests
│   ├── data/                         # Analytical data stores (SQLite)
│   └── frontend/                     # Legacy prototype UI (non-canonical)
│
├── data_access/                      # ★ Read-only data access layer (010-extract-pipeline)
│   ├── config.py                     # Config: ${EMSXVIEW_DATA_DIR} + DB/table constants
│   ├── storage/
│   │   ├── connection.py             # ConnectionManager (READ tier, sqlite mode=ro)
│   │   ├── market_store.py           # MarketStoreReader (bar data read)
│   │   ├── repositories/             # Read repositories (fills, raw_fills)
│   │   └── schema/                   # Schema package (column constants owned by pipeline repo)
│   ├── processing/                   # Read-side processing helpers (placeholder)
│   └── common/                       # exchange_tz and other read-side utilities
│
│   # 注：ETL 写入方（原 DataPipeline/）已迁独立仓库 EMSXDataPipeline；
│   #     本仓库为只读消费者，禁止 import DataPipeline.*，见 AGENTS.md
│
├── platform_data/                    # Cross-module shared adapters & contracts
│   ├── __init__.py                   # Public API surface
│   ├── pyproject.toml                # pip package: emsxview-platform-data
│   ├── config.py                     # HANDOFF_BACKEND, REDIS_URL config
│   ├── adapters/                     # Data adapters for cross-module communication
│   │   ├── handoff.py                # In-memory handoff (dict + threading.Lock)
│   │   ├── redis_handoff.py          # Redis pub/sub handoff (3 keys per contract)
│   │   ├── tca_bridge.py             # TCA query service registration bridge
│   │   └── market.py                 # Market reference data adapter
│   ├── contracts/                    # Cross-module data contracts
│   │   ├── handoff_contracts.py      # Handoff data schemas
│   │   ├── execution_contracts.py    # Execution data schemas
│   │   ├── tca_contracts.py          # TCA data schemas
│   │   ├── market_contracts.py       # Market data schemas
│   │   ├── intraday_contracts.py     # Intraday feature schemas
│   │   ├── protocols.py              # Interface protocols (ConnectionManager, Config)
│   │   └── db_constants.py           # Database constant definitions
│   ├── config_bridge.py              # Cross-module config bridge
│   └── regime_query.py               # Market regime query interface
│
│
├── docs/                             # Project documentation
│   ├── index.md                      # Documentation navigation guide
│   ├── api-contracts.md              # API contract specifications
│   ├── dev-guide.md                  # Developer guide
│   ├── schema-contract.md            # Schema contract docs
│   ├── api/                          # API reference docs
│   │   ├── bloomberg-emsx-reference.md
│   │   └── bloomberg-emsx-data-retrieval-methods.md
│   ├── spec/                         # Architecture specifications ★
│   │   ├── project-structure.md      # Canonical architecture reference
│   │   ├── data-domain.md            # Logical data domain design
│   │   └── memory.md                 # Architecture memory & constraints
│   ├── ops/                          # Operations docs
│   │   └── service-management.md     # Service operations guide
│   └── archive/                      # 归档（按日期或主题）
│       ├── 2026-06-29/               # eur_ticker_issue_analysis.md · database.md · sequence-diagrams.md
│       └── 2026-08-26/002-pipeline-guardrail/   # 管道护栏设计记录（被 plan-design-principles 引用）
│
│   # 注：一次性历史件（handoff/migration-baseline/architecture-analysis-report、
│   # legacy-costview-frontend 等）已于 2026-08-26 清理，见 git 历史与 ADR-0014
├── scripts/                          # Automation & utility scripts
│   ├── start-all.bat                 # Start all services
│   ├── stop-all.bat                  # Stop all services
│   ├── restart-all.bat               # Restart all services
│   ├── check-status.bat              # Check service health
│   ├── ops/
│   │   ├── service-manager.ps1       # PowerShell service manager
│   │   ├── cleanup-logs.ps1          # Log cleanup utility
│   │   ├── import_excel_fills.py     # Excel fill import
│   │   └── sync-metrics.py           # Metrics synchronization
│   ├── deploy/                       # Deployment scripts
│   ├── devtools/                     # Development tools
│   └── diagnose/                     # Diagnostic scripts
│
├── plans/                            # Project plans & policies
│   └── b4-remediation-plan.md
│
├── data/                             # Shared runtime data
├── logs/                             # Service logs (api, backfill, costview)
└── .github/                          # GitHub configuration
    └── knowledge/                     # Agent knowledge base
        ├── architecture-decisions.md  # Architecture decision records
        └── error-patterns.md          # Common error patterns
```

---

## Module Descriptions

### 1. frontend/ — React Frontend Shell

**Role:** The canonical single-page application shell hosting all functional modules.

- **Technology:** React 19.2, TypeScript 5.9, Vite 7.2, Tailwind CSS 3.4, shadcn/ui (Radix UI), Recharts 2.15
- **Architecture:** Module Registry pattern — each module self-registers via `moduleRegistry.register()` with id, label, order, and a lazy-loaded component. The shell discovers modules dynamically without hardcoding any module paths.
- **Modules:**
  - **execution/** (default, order: 0) — Order & Route management workspace with real-time WebSocket monitoring, batch operations, broker algorithm configuration, and compliance checks. Production-ready.
  - **marketview/** (order: 10) — Pre-trade market analysis shell anchor with intraday feature panels.
  - **costview/** (order: 20) — Post-trade TCA analysis UI with filtering, charts, scorecards, and export.
- **Shared Layer** (`src/shared/`) — ModuleRegistry, ShellContext, HTTP client, WebSocket client, auth token service, handoff API, and cross-module hooks.
- **Standalone Builds** — Each module can be built as an independent SPA via `npm run build:execution`, `build:costview`, `build:marketview`.

---

### 2. backend/api/ — Core Execution Backend

**Role:** Central API service for order/route management with Bloomberg EMSX integration.

- **Technology:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy, blpapi 3.23
- **Service Port:** `<API_PORT>` (core, always running; default 3000, override via `API_PORT`)
- **Key Capabilities:**
  - Order CRUD operations with parent/child execution scheduling
  - Route management with batch operations and broker strategy configuration
  - Real-time WebSocket push for order/route state streaming
  - JWT authentication and authorization
  - Bloomberg EMSX API integration (async background connection, 30-120s BPIPE init)
  - Pre-trade compliance checks (USD notional bounds, odd lots)
  - Route plan management and algorithm scheduling
  - Market-to-broker strategy mapping
- **Core Routers** (always loaded): connection, auth, orders, routes, broker, realtime, debug, route_plans, market_broker_mapping
- **Optional Routers**: costview (CostView bridge; registered via `_register_optional`)

> DatabaseView API 与 Execution History API 已随 010-extract-pipeline 移除（数据库维护迁独立仓库 EMSXDataPipeline）。
- **Bloomberg Service** (`services/bloomberg/`) — Split package with connection lifecycle management, order/route subscriptions with cache, market data enrichment (FX, round lot, permfail detection), and CRUD request handling.
- **RepositoryProvider** — DB vs. in-memory fallback gated behind `ENABLE_DB_PERSISTENCE` flag.

---

### 3. MarketView/ — Pre-Trade Market Analysis

**Role:** Market data analysis and pre-trade decision support microservice.

- **Technology:** Python 3.11, FastAPI
- **Service Port:** `<MARKETVIEW_PORT>` (standalone or merged; default 8001, override via `MARKETVIEW_PORT`)
- **No Bloomberg dependency** — operates on previously ingested market data
- **Key Capabilities:**
  - Market snapshot API (daily close, volatility, volume, ADV)
  - Intraday feature data
  - Handoff contracts to push analysis results into execution module
- **Status:** Shell anchor in place — domain capabilities being built incrementally

---

### 4. CostView/ — Post-Trade TCA Analysis

**Role:** Transaction cost analysis, execution quality measurement, and performance reporting.

- **Technology:** Python 3.11, FastAPI
- **Service Port:** `<COSTVIEW_PORT>` (standalone or merged; default 8002, override via `COSTVIEW_PORT`)
- **No Bloomberg dependency** — read-only analytical queries against the data stores exposed by `data_access/`
- **Key Capabilities:**
  - TCA analysis queries (Implementation Shortfall, VWAP, TWAP benchmarks)
  - Trigger pipeline data updates on demand
  - Asynchronous job status tracking
  - Broker performance ranking and recommendations
  - Cost attribution analysis
  - CLI query interface (`python -m CostView.src --date YYYY-MM-DD`)
- **Analytical Engine** (`src/`) — `TcaQueryService`, `TcaQueryBuilder`, fallback processing, secure config

---

### 5. data_access/ — Read-Only Data Access Layer

**Role:** Read-side access to the analytical data stores (SQLite). EMSXView is a **pure read consumer**: the ETL write side lives in the separate EMSXDataPipeline repository.

- **Technology:** Python 3.11, sqlite3 (`mode=ro` URI), numpy
- **Entry Point:** `data_access.config.Config` + `data_access.ConnectionManager` (READ tier only; WRITE/admin requests are rejected)
- **Configuration** — Data root resolves in this order: `${EMSXVIEW_DATA_DIR}` env var > default `D:\db` (`Config.DEFAULT_DATA_DIR`). All DB paths, table names and SQLite settings come from `data_access/config.py`; hardcoding them elsewhere is prohibited.
- **Data Stores** (under `${EMSXVIEW_DATA_DIR}`) — `raw_fills.db`, `processed_fills.db`, `raw_bdib.db`, `processed_raw_bdib.db`, `fill_bdib.db`, `fill_fetch_history.db`, `bdib_fetch_history.db`, `execution_history.db`, `ticker_registry.db`
- **Read Surface** — `ConnectionManager` (READ tier), `MarketStoreReader`, `SqliteFillReadRepository`, `SqliteRawFillReadRepository`
- **Write Side** — Data refresh/maintenance is performed by the EMSXDataPipeline repository runner (`POST /run`, `GET /status`); this repository never writes.

---

### 6. platform_data/ — Cross-Module Shared Adapters

**Role:** Shared adapter layer bridging operational and analytical domains across all modules.

- **Technology:** Python 3.11, Pydantic v2
- **Adapters:**
  - `HandoffAdapter` — In-memory (dict + threading.Lock) or Redis pub/sub cross-module data handoff
  - `TcaBridge` — TCA service registration and query routing
  - `MarketReferenceDataAdapter` — Market snapshot and reference data
- **Contracts** — 7+ contract files defining typed schemas for handoff, execution, TCA, market, intraday data
- **Protocols** — `ConnectionManagerProtocol`, `ConfigProtocol` for interface-based dependency injection
- **Services** — `ExecutionHistoryService`, `PipelineJobs`, `RegimeQuery`, `DatabaseDiagnostics`

---

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Frontend Shell** | React 19.2, TypeScript 5.9, Vite 7.2 |
| **UI Framework** | Tailwind CSS 3.4, shadcn/ui (Radix UI primitives) |
| **Visualization** | Recharts 2.15 |
| **Forms & Validation** | react-hook-form 7.70, zod 4.3 |
| **State Management** | React Context + Zustand (stream stores) |
| **Backend** | Python 3.11, FastAPI, Pydantic v2 |
| **Bloomberg API** | blpapi 3.19+, xbbg 0.7+ |
| **ORM** | SQLAlchemy 2.x |
| **Authentication** | JWT (PyJWT, passlib) |
| **Real-time** | WebSocket (FastAPI + browser native) |
| **Data Processing** | pandas, numpy |
| **Operational DB** | PostgreSQL (optional, for order/route persistence) |
| **Analytical DB** | SQLite (6 databases for pipeline data) |
| **Cache & Messaging** | Redis 7 (production handoff + caching) |
| **Reverse Proxy** | Nginx 1.27 |
| **Monitoring** | Prometheus + Grafana (optional profile) |
| **Containerization** | Docker Compose (8 services) |
| **Package Management** | npm (frontend), pip + setuptools/pyproject.toml (Python) |
| **Scripting** | PowerShell, Batch, Python CLI |

### Python Package Dependencies

```
emsxview-platform-data   ← pydantic, python-dateutil
emsxview-costview        ← pydantic, emsxview-platform-data
```

> `data_access/` 是仓库内模块（非独立 pip 包），零第三方配置依赖；原 `emsxview-datapipeline` 包已随 010-extract-pipeline 迁出至独立仓库。

---

## Installation & Running

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

- **Bloomberg Terminal** with API enabled (required for live execution & data pipeline)
- **Node.js 20+** (for frontend development)
- **Python 3.11+** (for backend & pipeline)
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
npm run test:watch              # vitest watch mode

# Standalone module builds
npm run build:execution         # Build execution module SPA → dist/execution/
npm run build:costview          # Build costview module SPA → dist/costview/
npm run build:all-modules       # Build all module SPAs at once
```

Environment variables (`frontend/.env`):
- `VITE_API_URL=` — Backend URL (empty = mock/no backend), e.g. `http://<host>:<API_PORT>`
- `VITE_USE_MOCK=true` — Enable mock Bloomberg data

### Backend Development (Core)

```bash
cd <repo-root>/backend/api
pip install -r requirements.txt          # Includes -e ../../platform_data

# Single-process mode (all modules, recommended for dev)
set EMSXVIEW_MERGE_MODULES=true
python main.py                           # Starts on <API_PORT> (default 3000)

# Or use uvicorn directly
uvicorn main:app --port <API_PORT> --reload

# Run tests
pytest
```

Environment variables (`backend/.env`):
- `BLOOMBERG_HOST`, `BLOOMBERG_PORT` — Bloomberg SAPI connection
- `JWT_SECRET` — JWT signing key
- `EMSXVIEW_MERGE_MODULES` — `true` for single-process, `false` for microservice
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

EMSXView consumes the analytical SQLite stores through `data_access/`; it never writes.

```bash
# 数据根解析优先级：${EMSXVIEW_DATA_DIR} > data_access.config.Config.DEFAULT_DATA_DIR
# Windows
set EMSXVIEW_DATA_DIR=<data-dir>        # 例：D:\db
# Linux / macOS
export EMSXVIEW_DATA_DIR=<data-dir>

# 只读连接自检（READ tier；任何写请求会被拒绝）
python -c "from data_access import ConnectionManager, Config; print(Config.DATA_DIR)"

# Run CostView TCA for a specific date
python -m CostView.src --date 2024-01-15

# Initial config setup
python -m CostView.src --setup-config

# Run CostView tests
python -m pytest CostView/tests/
```

> 数据更新维护（ETL 写入方）已迁独立仓库 EMSXDataPipeline，通过其 Runner（`POST /run`、`GET /status`）触发；本仓库无 `python -m DataPipeline` 入口。

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
| redis | 6379 | 未映射宿主端口（仅 compose 网络内） | Cache + pub/sub | — |
| prometheus (opt) | 9090 | `${PROMETHEUS_PORT:-9090}:9090` | Metrics collection | `PROMETHEUS_PORT` |
| grafana (opt) | 3000 | `${GRAFANA_PORT:-3001}:3000` | Dashboards | `GRAFANA_PORT` |

Nginx routes: `/api/*` → backend `<API_PORT>`, `/ws/*` → backend `<API_PORT>`, `/*` → frontend static files.

---

## Cross-Module Communication

### Handoff Protocol

Handoff data transfers between modules use `platform_data/adapters/`:

```
MarketView ──handoff──▶ ExecutionView ◀──recommendations── CostView
   (candidates)           (shared state)         (order recs)
```

- **In-memory** (`HANDOFF_BACKEND=memory`): Process-local dict with threading.Lock — used in single-process/dev mode
- **Redis** (`HANDOFF_BACKEND=redis`): Redis pub/sub with 3 keys/data per contract — used in microservice/production mode
- Frontend handoff state managed via `useHandoffContracts()` hook and `handoff-api.ts` service

### Module Registry (Frontend)

All frontend modules self-register via `moduleRegistry.register()` in `module.registry.ts`. The shell dynamically discovers and renders them:

```
ModuleRegistry (singleton)
├── execution   (order: 0, default, WS: /ws/orders, handoffBadge)
├── marketview  (order: 10)
└── costview    (order: 20)
```

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | One-command Windows service launcher |
| [CODEBUDDY.md](./CODEBUDDY.md) | Agent guidance with build/test commands |
| [docs/spec/project-structure.md](./docs/spec/project-structure.md) | Canonical architecture reference |
| [docs/spec/data-domain.md](./docs/spec/data-domain.md) | Logical data domain design |
| [docs/spec/memory.md](./docs/spec/memory.md) | Architecture memory & constraints |
| [docs/dev-guide.md](./docs/dev-guide.md) | Developer guide |
| [docs/schema-contract.md](./docs/schema-contract.md) | Cross-module type contracts (TS ↔ Python) |
| [docs/index.md](./docs/index.md) | Documentation navigation |
| [docs/ops/service-management.md](./docs/ops/service-management.md) | Service operations & troubleshooting |
| [backend/README.md](./backend/README.md) | Backend production deployment guide |
| [CostView/README.md](./CostView/README.md) | CostView module details |
| [MarketView/README.md](./MarketView/README.md) | MarketView module details |
| [scripts/README.md](./scripts/README.md) | Automation scripts reference |

---

*Last updated: September 7, 2026*
