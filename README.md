# EMSXView Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis, order execution, and post-trade TCA analytics**

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
│  │    :8001        │   │    :3000        │   │    :8002        │            │
│  └────────┬────────┘   └───────┬─────────┘   └───────┬─────────┘            │
│           │                    │                     │                      │
│           ▼                    ▼                     ▼                      │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      Shared Infrastructure                           │   │
│  │  frontend/ (React shell)  ·  platform_data/ (adapters & contracts)   │   │
│  │  DataPipeline/ (ETL)     ·  PostgreSQL + SQLite  ·  Redis + Nginx    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

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
| **Microservice** (production) | `false` (default) | Core :3000, MarketView :8001, CostView :8002 |
| **Single-process** (dev/demo) | `true` | All modules in one process on :3000 |

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
├── 重启服务.bat                       # One-click restart
│
├── frontend/                         # ★ Canonical React frontend shell
│   ├── package.json                  # npm: emsxview-trading-tool
│   ├── vite.config.ts                # Main Vite config (dev server :5173)
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
│       │   ├── marketview/           # Pre-trade shell anchor
│       │   │   ├── MarketViewModule.tsx
│       │   │   ├── intraday-feature-panel.tsx
│       │   │   └── services/
│       │   └── databaseview/         # Database admin UI
│       │       └── DatabaseViewModule.tsx
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
│       ├── main.py                   # FastAPI application entry (:3000)
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
│       │   ├── debug.py              # Debug endpoints
│       │   ├── database.py           # DatabaseView API (optional)
│       │   └── execution_history.py  # Execution history API (optional)
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
├── MarketView/                       # Pre-trade microservice (:8001)
│   ├── main.py                       # FastAPI entry (no Bloomberg dependency)
│   ├── config.py
│   └── routers/
│       └── marketview.py             # Market snapshot & intraday features API
│
├── CostView/                         # Post-trade TCA microservice (:8002)
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
├── DataPipeline/                     # Data platform subsystem (ETL + Analysis)
│   ├── __main__.py                   # CLI: python -m DataPipeline --once
│   ├── config.py                     # ★ Single source of truth for pipeline config
│   │                                 #    DB paths, table names, date formats, SQLite settings
│   ├── pyproject.toml                # pip package: emsxview-datapipeline
│   ├── orchestration/                # Multi-stage pipeline orchestrator
│   │   ├── core.py                   # run_full_pipeline() entry point
│   │   ├── context.py                # Pipeline execution context
│   │   ├── stages_ingest.py          # Ingest: fetch fills from Bloomberg EMSX
│   │   ├── stages_process.py         # Process: clean, aggregate, integrate with BDIB
│   │   └── stages_analysis.py        # Analyze: TCA, regime detection, attribution
│   ├── ingestion/                    # Data acquisition
│   │   ├── fill_fetch.py             # EMSX fill retrieval with SHA-256 dedup
│   │   ├── fill_ingestion.py         # Raw fill ingestion pipeline
│   │   ├── bdib_fetcher.py           # BDIB market bar fetcher
│   │   └── emsx_client.py            # EMSX API client
│   ├── processing/                   # Data processing
│   │   ├── fill_cleaner.py           # Fill data cleaning
│   │   ├── fill_processor.py         # Fill processing pipeline
│   │   ├── fill_aggregator.py        # Time-based aggregation (10s, 1min)
│   │   ├── fill_bdib_integrated.py   # Fill + BDIB bar integration
│   │   ├── daily_metrics_calculator.py  # Daily summary metrics
│   │   ├── order_label.py            # Order labeling/linking
│   │   └── validate_raw_fills.py     # Raw fill validation
│   ├── analysis/                     # Analytics engine
│   │   ├── attribution/              # Cost attribution analysis
│   │   │   ├── aggregator.py         # Cost aggregation
│   │   │   ├── benchmarks.py         # Benchmark calculations
│   │   │   ├── metrics.py            # Performance metrics
│   │   │   ├── recommender.py        # Broker recommendation engine
│   │   │   └── writer.py             # Analysis output writer
│   │   └── regime/                   # Market regime classification (16 files)
│   │       ├── fill_regime_tagger.py      # Tag fills with regime labels
│   │       ├── liquidity_regime.py        # Liquidity regime detection
│   │       ├── trend_regime.py            # Trend regime detection
│   │       ├── vol_regime.py              # Volatility regime detection
│   │       ├── market_index_loader.py     # Market index data loading
│   │       └── sync_macro_calendar.py     # Macro calendar synchronization
│   ├── storage/                      # Data persistence layer
│   │   ├── connection.py             # ConnectionManager (6 SQLite databases)
│   │   ├── facade.py                 # DatabaseFacade (unified query interface)
│   │   ├── repositories/             # Typed repository layer (fills, market_data, regime, etc.)
│   │   └── schema/                   # Database schema definitions
│   └── common/                       # Shared pipeline utilities
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
│   ├── execution_history_service.py  # Historical execution queries
│   ├── pipeline_jobs.py              # Pipeline job management
│   ├── regime_query.py               # Market regime query interface
│   └── database_diagnostics.py       # Database diagnostics utility
│
│
├── docs/                             # Project documentation
│   ├── index.md                      # Documentation navigation guide
│   ├── api-contracts.md              # API contract specifications
│   ├── HANDOFF.md                    # Handoff protocol documentation
│   ├── dev-guide.md                  # Developer guide
│   ├── architecture-analysis-report.md  # Architecture analysis
│   ├── final-refactoring-plan.md     # Refactoring roadmap
│   ├── migration-baseline.md         # Migration baseline
│   ├── schema-contract.md            # Schema contract docs
│   ├── api/                          # API reference docs
│   │   ├── bloomberg-emsx-reference.md
│   │   ├── bloomberg-emsx-data-retrieval-methods.md
│   │   ├── database.md
│   │   └── sequence-diagrams.md
│   ├── spec/                         # Architecture specifications ★
│   │   ├── project-structure.md      # Canonical architecture reference
│   │   ├── data-domain.md            # Logical data domain design
│   │   └── memory.md                 # Architecture memory & constraints
│   ├── ops/                          # Operations docs
│   │   └── service-management.md     # Service operations guide
│   └── roadmap/                      # Roadmap & WBS
│       ├── wbs.md
│       └── task-templates.md
│
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
│   ├── workflow/                     # CI/CD workflow scripts
│   │   ├── workflow_engine.py
│   │   ├── auto_runner.py
│   │   ├── sync_execution_status.py
│   │   └── validate_phase_gate.py
│   ├── deploy/                       # Deployment scripts
│   ├── devtools/                     # Development tools
│   └── diagnose/                     # Diagnostic scripts
│
├── plans/                            # Project plans & policies
│   ├── architecture-refactor-workflow.yaml
│   ├── execution-platform-autopilot-policy.yaml
│   ├── execution-platform-risk-register.yaml
│   └── execution-platform-status.yaml
│
├── data/                             # Shared runtime data
├── logs/                             # Service logs (api, backfill, costview, workflow)
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
  - **databaseview/** (order: 30) — Database admin and diagnostics UI.
- **Shared Layer** (`src/shared/`) — ModuleRegistry, ShellContext, HTTP client, WebSocket client, auth token service, handoff API, and cross-module hooks.
- **Standalone Builds** — Each module can be built as an independent SPA via `npm run build:execution`, `build:costview`, `build:marketview`, `build:databaseview`.

---

### 2. backend/api/ — Core Execution Backend

**Role:** Central API service for order/route management with Bloomberg EMSX integration.

- **Technology:** Python 3.11, FastAPI, Pydantic v2, SQLAlchemy, blpapi 3.23
- **Service Port:** :3000 (core, always running)
- **Key Capabilities:**
  - Order CRUD operations with parent/child execution scheduling
  - Route management with batch operations and broker strategy configuration
  - Real-time WebSocket push for order/route state streaming
  - JWT authentication and authorization
  - Bloomberg EMSX API integration (async background connection, 30-120s BPIPE init)
  - Pre-trade compliance checks (USD notional bounds, odd lots)
  - Route plan management and algorithm scheduling
  - Market-to-broker strategy mapping
  - Optional modules: DatabaseView API, Execution History API
- **Core Routers** (always loaded): connection, auth, orders, routes, broker, realtime, debug, route_plans, market_broker_mapping
- **Optional Routers**: marketview (merge mode only), costview (merge mode only), database, execution_history
- **Bloomberg Service** (`services/bloomberg/`) — Split package with connection lifecycle management, order/route subscriptions with cache, market data enrichment (FX, round lot, permfail detection), and CRUD request handling.
- **RepositoryProvider** — DB vs. in-memory fallback gated behind `ENABLE_DB_PERSISTENCE` flag.

---

### 3. MarketView/ — Pre-Trade Market Analysis

**Role:** Market data analysis and pre-trade decision support microservice.

- **Technology:** Python 3.11, FastAPI
- **Service Port:** :8001 (standalone or merged)
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
- **Service Port:** :8002 (standalone or merged)
- **No Bloomberg dependency** — analytical queries against pipeline data stores
- **Key Capabilities:**
  - TCA analysis queries (Implementation Shortfall, VWAP, TWAP benchmarks)
  - Trigger pipeline data updates on demand
  - Asynchronous job status tracking
  - Broker performance ranking and recommendations
  - Cost attribution analysis
  - CLI query interface (`python -m CostView.src --date YYYY-MM-DD`)
- **Analytical Engine** (`src/`) — `TcaQueryService`, `TcaQueryBuilder`, fallback processing, secure config

---

### 5. DataPipeline/ — Data Platform Subsystem

**Role:** Multi-stage ETL pipeline for trade data acquisition, processing, and analytics.

- **Technology:** Python 3.11, pandas, numpy, blpapi, xbbg
- **Entry Point:** `python -m DataPipeline --once` or programmatic `run_full_pipeline()`
- **Pipeline Stages:**
  1. **Ingestion** — Fetch fills from Bloomberg EMSX with SHA-256 deduplication; also fetches BDIB intraday bars, FX rates
  2. **Processing** — Clean fills, aggregate (10s/1min buckets), integrate fills with BDIB bars, compute daily metrics
  3. **Analysis** — TCA cost attribution, market regime classification (liquidity/trend/volatility), broker recommendations
- **Storage Layer** — `ConnectionManager` manages 6 SQLite databases: `raw_fills.db`, `processed_fills.db`, `fill_bdib.db`, `market_data.db`, `regime.db`, `fetch_history.db`
- **Configuration** — All DB paths, table names, date formats, and SQLite settings centralized in `DataPipeline/config.py`
- **Market Regime Engine** — Classifies each trade window by liquidity regime, volatility regime, and trend regime using market index data and macro event calendars.

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
| **Authentication** | JWT (python-jose, passlib) |
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
emsxview-datapipeline    ← blpapi, pandas, numpy, xbbg
emsxview-platform-data   ← pydantic, python-dateutil, emsxview-datapipeline
emsxview-costview        ← pydantic, emsxview-platform-data, emsxview-datapipeline
```

---

## Installation & Running

### Quick Start (Windows)

```bash
# One-command launch (see QUICKSTART.md for details)
scripts\start-all.bat

# Check service health
scripts\check-status.bat
```

Service URLs:
| Service | URL |
|---------|-----|
| Frontend (dev) | http://localhost:5173 |
| Core Backend | http://localhost:3000 |
| API Docs (Swagger) | http://localhost:3000/docs |
| MarketView | http://localhost:8001/docs |
| CostView | http://localhost:8002/docs |
| Health Check | http://localhost:3000/api/health |

### Prerequisites

- **Bloomberg Terminal** with API enabled (required for live execution & data pipeline)
- **Node.js 20+** (for frontend development)
- **Python 3.11+** (for backend & pipeline)
- **Docker Desktop 4.x** (for production deployment)

### Frontend Development

```bash
cd frontend
npm install
npm run dev                     # Dev server on http://localhost:5173
                                # Mock mode if VITE_API_URL is empty

npm run build                   # Production build → dist/
npm run lint                    # ESLint
npm test                        # vitest run
npm run test:watch              # vitest watch mode

# Standalone module builds
npm run build:execution         # Build execution module SPA → dist/execution/
npm run build:costview          # Build costview module SPA → dist/costview/
npm run build:all-modules       # Build all four modules at once
```

Environment variables (`frontend/.env`):
- `VITE_API_URL=` — Backend URL (empty = mock/no backend)
- `VITE_USE_MOCK=true` — Enable mock Bloomberg data

### Backend Development (Core)

```bash
cd backend/api
pip install -r requirements.txt          # Includes -e ../../platform_data

# Single-process mode (all modules, recommended for dev)
set EMSXVIEW_MERGE_MODULES=true
python main.py                           # Starts on :3000

# Or use uvicorn directly
uvicorn main:app --port 3000 --reload

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
# MarketView standalone (:8001, no Bloomberg)
cd MarketView
pip install -r requirements.txt
python main.py

# CostView standalone (:8002, no Bloomberg)
pip install -e CostView
cd CostView/api
pip install -r requirements.txt
python main.py
```

### Data Pipeline

```bash
pip install -e DataPipeline
pip install -e CostView

# Run full pipeline once
python -m DataPipeline --once

# Run CostView TCA for a specific date
python -m CostView.src --date 2024-01-15

# Initial config setup
python -m CostView.src --setup-config

# Run pipeline tests
python -m pytest CostView/tests/
```

### Docker (Production)

```bash
cd backend

# Full stack: backend + postgres + frontend (Nginx) + redis
docker compose up -d

# With host-network (local Bloomberg Terminal)
docker compose -f docker-compose.host.yml up -d

# With monitoring (Prometheus + Grafana)
docker compose --profile monitoring up -d
```

Docker Compose services:
| Service | Port | Purpose |
|---------|------|---------|
| backend | :3000 | FastAPI core |
| postgres | :5432 | Operational DB |
| frontend (Nginx) | :80 | SPA + reverse proxy |
| redis | :6379 | Cache + pub/sub |
| prometheus (opt) | :9090 | Metrics collection |
| grafana (opt) | :3001 | Dashboards |

Nginx routes: `/api/*` → backend :3000, `/ws/*` → backend :3000, `/*` → frontend static files.

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
├── costview    (order: 20)
└── database    (order: 30)
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
| [docs/HANDOFF.md](./docs/HANDOFF.md) | Cross-module handoff protocol |
| [docs/index.md](./docs/index.md) | Documentation navigation |
| [docs/ops/service-management.md](./docs/ops/service-management.md) | Service operations & troubleshooting |
| [backend/README.md](./backend/README.md) | Backend production deployment guide |
| [CostView/README.md](./CostView/README.md) | CostView module details |
| [MarketView/README.md](./MarketView/README.md) | MarketView module details |
| [scripts/README.md](./scripts/README.md) | Automation scripts reference |

---

*Last updated: May 29, 2026*
