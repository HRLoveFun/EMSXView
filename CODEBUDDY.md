# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

EMSXView (Execution Management System eXtended View) is a Bloomberg EMSX-integrated trading platform covering pre-trade analysis, order execution, and post-trade TCA analytics. It is a monorepo with three business modules sharing a single React frontend shell and a Python data pipeline.

### Deployment Modes

The backend supports two deployment modes controlled by `EMSXVIEW_MERGE_MODULES`:

| Mode | Env Var | Architecture |
|------|---------|-------------|
| **Microservice** (production) | `false` (default) | Core :3000, MarketView :8001, CostView :8002 |
| **Single-process** (dev/demo) | `true` | All modules in one process on :3000 |

Cross-module handoff uses configurable backend (`EMSXVIEW_HANDOFF_BACKEND`):
- `memory` (default): In-process, single-process mode
- `redis`: Redis-backed, cross-process for microservice mode

## Build & Run Commands

### Frontend (frontend/)

```bash
cd frontend
npm install          # Install dependencies
npm run dev          # Dev server on :5173 (mock mode if VITE_API_URL is empty)
npm run build        # tsc -b && vite build → dist/
npm run lint         # ESLint
npm test             # vitest run
npm run test:watch   # vitest watch

# 运行单个测试文件
npx vitest run src/modules/execution/__tests__/order-table.test.tsx

# 按名称匹配运行测试
npx vitest run -t "should render order table" src/
```

- Vite proxies `/api/*` and `/ws/*` to `http://localhost:3000` in dev mode.
- `VITE_USE_MOCK=true` enables mock Bloomberg data when no backend is running.

### Backend (backend/api)

```bash
cd backend/api
pip install -r requirements.txt    # Includes -e ../../platform_data
python main.py                     # Starts uvicorn on :3000 (core only in microservice mode)
uvicorn main:app --port 3000       # Alternative
set EMSXVIEW_MERGE_MODULES=true    # Enable single-process mode for dev
pytest                             # 运行全部后端测试
pytest -v                          # 带详细输出
pytest -k "test_create_order" -v   # 按名称匹配运行单个测试
pytest tests/test_orders.py -v     # 运行特定测试文件
```

### MarketView Standalone (:8001)

```bash
cd MarketView
pip install -r requirements.txt
python main.py                     # Starts on :8001 (no Bloomberg dependency)
```

### CostView Standalone (:8002)

```bash
pip install -e CostView            # Install emsxview-costview package
cd CostView/api
pip install -r requirements.txt
python main.py                     # Starts on :8002 (no Bloomberg dependency)
```

### DataPipeline / CostView

```bash
cd DataPipeline
pip install -e .                 # Install pipeline package

cd ../CostView
pip install -r requirements.txt
python -m CostView.src --date 2024-01-15       # Run fill fetch for a date
python -m CostView.src --setup-config          # Initial config setup
python -m pytest CostView/tests/               # Run pipeline tests
```

### Docker (Production)

```bash
cd backend
docker compose up -d                                        # Full stack
docker compose -f docker-compose.host.yml up -d             # Host-network mode (local Bloomberg)
docker compose --profile monitoring up -d                   # With Prometheus + Grafana
```

### Windows Service Scripts

```bash
scripts\start-all.bat     # Start all services
scripts\stop-all.bat      # Stop all services
scripts\restart-all.bat   # Restart all services
scripts\check-status.bat  # Check service health
```

## Architecture

### Module Flow (Trade Lifecycle)

```
MarketView (Pre-Trade) → ExecutionView (Order Execution) → CostView (Post-Trade TCA)
```

All module UIs are mounted in a **single** React shell via `ModuleRegistry` — each module self-registers with id/label/loader. The shell discovers modules dynamically without hardcoding any module paths.

**Module discovery pattern**:
- Each module exports a `module.registry.ts` that calls `moduleRegistry.register(...)`
- `App.tsx` imports all registries as side effects before `AppShell` renders
- `WorkspaceModuleTabs` renders tabs from `moduleRegistry.getAll()`
- Modules receive shell services via `useShellContext()` React context

**Standalone module builds** (independent deployment):
```bash
npm run build:execution     # ExecutionView SPA → dist/execution/
npm run build:costview      # CostView SPA → dist/costview/
npm run build:marketview    # MarketView SPA → dist/marketview/
npm run build:databaseview  # DatabaseView SPA → dist/database/
npm run build:all-modules   # All four at once
```

### Frontend — Shell + Lazy-Loaded Modules

- **AppShell** (`src/app/AppShell.tsx`) — root layout orchestrator with toolbar, module tabs, and toast container
- Four lazy-loaded React modules under `src/modules/`:
  - `execution/` — order tables, route tables, monitoring, batch operations
  - `costview/` — post-trade TCA UI (canonical)
  - `marketview/` — pre-trade market snapshot (shell anchor)
  - `databaseview/` — database admin/diagnostics
- Vite manual chunking ensures each module gets its own bundle (`module-costview`, `module-marketview`, etc.)
- Shared code lives in `src/shared/` (hooks, lib, services, types) and `src/components/` (React components)
- API client services live in each module's `services/` directory (e.g. `modules/execution/services/execution-api.ts`, `modules/costview/services/api.ts`)

**Path aliases** (configured in both vite.config.ts and tsconfig.app.json):
- `@/*` → `./src/*`
- `@app/*` → `./src/app/*`
- `@shared/*` → `./src/shared/*`
- `@execution/*` → `./src/modules/execution/*`
- `@costview/*` → `./src/modules/costview/*`
- `@marketview/*` → `./src/modules/marketview/*`
- `@databaseview/*` → `./src/modules/databaseview/*`

### Backend — Layered FastAPI (Multi-Process)

```
Core Service (:3000):                 MarketView (:8001):      CostView (:8002):
orders, routes, broker (Bloomberg)    marketview.py            costview.py
route_plans, realtime, auth           (no Bloomberg)           (no Bloomberg)
connection, debug, mappings
```

- Entry point: `backend/api/main.py`
- **Core routers** (always loaded): connection, auth, orders, routes, broker, realtime, debug, route_plans, market_broker_mapping
- **Optional routers**: database (DatabaseView)
- **Independent services**: `MarketView/main.py` (:8001), `CostView/api/main.py` (:8002)
- **Merge mode** (`EMSXVIEW_MERGE_MODULES=true`): All routers in single process (dev/demo)
- Key services: `BloombergEMSXService` (Bloomberg API adapter), `AuthService`, `RouteService`, `ComplianceService`
- `RepositoryProvider` gates DB reads/writes behind `ENABLE_DB_PERSISTENCE` flag
- Bloomberg connection starts as an async background task (can take 30-120s for BPIPE initialization)

### Cross-Module Communication

Handoff between modules uses `platform_data/adapters.py` → `HandoffExchangeAdapter`:
- **In-memory** (`HANDOFF_BACKEND=memory`): Process-local dict + threading.Lock (single-process mode)
- **Redis** (`HANDOFF_BACKEND=redis`): Redis pub/sub (microservice mode, 3 keys per contract)
- `get_shared_handoff_exchange()` returns the configured adapter transparently

### DataPipeline — Stage-Based Processing

`DataPipeline/orchestration/` runs a multi-stage pipeline:

1. **Ingestion** (`stages_ingest.py`): Fetch fills from Bloomberg EMSX, ingest raw fills
2. **Processing** (`stages_process.py`): Clean, aggregate, integrate with BDIB (intraday bars), compute daily metrics
3. **Analysis** (`stages_analysis.py`): TCA, regime detection, attribution

Data flows through SQLite databases: `raw_fills.db` → `processed_fills.db` → `fill_bdib.db` → `bdib_daily_summary`

All pipeline configuration is centralized in `DataPipeline/config.py` (Config class with DB paths, table names, date formats). Data directory is configurable via `EMSXVIEW_DATA_DIR` env var, defaulting to `CostView/data`.

### platform_data/ — Cross-Module Adapters

Shared logical data-domain adapters bridging modules:
- `CostViewAnalyticsAdapter` — TCA query interface
- `CostViewDatabaseAdapter` — direct DB access for CostView
- `MarketReferenceDataAdapter` — market snapshot data
- `ExecutionHistoryAdapter` — historical execution data
- `HandoffExchangeAdapter` — cross-module data handoff
- `DataPlatformIngestionAdapter` — pipeline ingestion interface

### Infrastructure

Docker Compose (production) runs: backend (FastAPI :3000), postgres (:5432), frontend (Nginx :80), redis, prometheus (optional), grafana (optional). Nginx reverse-proxies `/api/*` and `/ws/*` to the backend.

## Key Conventions

### TypeScript / React 编码规范

- 优先使用 `const`，避免 `let`，禁止 `var`
- 使用箭头函数，除非需要 `this` 绑定
- 优先使用函数式编程范式（map/filter/reduce）
- 每个函数不超过 30 行，使用 early return 减少嵌套
- **所有注释使用中文**
- 使用 `interface` 定义对象类型，使用 `type` 定义联合类型和工具类型
- 为所有函数参数和返回值添加类型注解
- Frontend uses **shadcn/ui** components (Radix UI + Tailwind CSS). New UI components should follow the same pattern — use `npx shadcn@latest add <component>` to add new shadcn components.
- TypeScript strict mode is enabled (`noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`, `strictNullChecks`).

### 前端状态管理

- 全局应用状态使用 React Context（ShellContext 通过 `useShellContext()` 访问）
- 实时数据流（订单/路由）使用 Zustand store（`order-stream-store`、`route-stream-store`）
- 跨模块通信：`ModuleRegistry` 注册 + `useHandoffContracts()` hook + `handoff-api.ts` 服务

### 后端约定

- Backend uses Pydantic v2 models for schemas; all API responses wrapped in `ApiResponse`.
- 使用 `Depends()` 进行依赖注入（参见 `deps.py`）
- 数据库读写由 `RepositoryProvider` 统一控制，gate 为 `ENABLE_DB_PERSISTENCE` 标志
- Pipeline config is the single source of truth — do not hardcode DB paths or table names; import from `DataPipeline/config.Config`.
- Backend optional routers must never break the core ExecutionView — use the `_register_optional` pattern in `main.py`.

### 启动器与项目根路径（★ 必须遵守）

- 项目根定位**唯一信息源**是仓库根的 `.emsxview-root` marker 文件；新增/修改 `scripts/deploy/` 下启动脚本时**必须**用 `Find-EmsxviewRoot`（向上查找 marker），**禁止**硬编码"向上 N 层"
- 启动器算出项目根后**必须** `Assert-ProjectRootValid` 自检，错路径立即 throw，**禁止**进入 120s 超时黑盒
- VBS 启动器只做 thin wrapper（隐藏窗口 + 调起 PS1），**禁止**在 VBS 内做路径深度计算或业务逻辑——`WScript.ScriptFullName` 含文件名、`$PSScriptRoot` 已是目录，两者语义不可复用同一套"向上 N 层"
- 详见 [AP-16 启动器路径硬编码 + 跨宿主语义错位](docs/spec/anti-patterns.md#ap-16-启动器路径硬编码--跨宿主语义错位)

## Refactoring Context

当前分支 `data_management_refactoring` 正在进行数据管理重构。在执行任何涉及数据库、存储或数据管道层的更改前，必须先查阅：

1. `AGENTS.md` — 重构工作流规范（含安全规则）
2. `data_management_refactoring_control.md` — 当前进度和任务状态
3. `data_management_refactoring_plan.md` — 详细实施方案

<!-- SPECKIT START -->
## Current Plan

**Feature**: 数据管道护栏机制
**Branch**: `001-architecture-module-completion`
**Plan**: `specs/002-pipeline-guardrail/plan.md`
**Spec**: `specs/002-pipeline-guardrail/spec.md`

Key artifacts:
- `specs/002-pipeline-guardrail/research.md` — 熔断器模式、Pydantic 校验、基线测试、契约检查、日志方案研究
- `specs/002-pipeline-guardrail/data-model.md` — PipelineRun、StageExecution、ValidationViolation、CircuitBreakerState、PipelineSchema 实体定义
- `specs/002-pipeline-guardrail/contracts/guard-pipeline-api.md` — GuardPipeline、Validator、CircuitBreaker、PipelineRunLogger API 契约
- `specs/002-pipeline-guardrail/quickstart.md` — 10 个验证场景，覆盖校验/熔断/完整性/契约/日志
<!-- SPECKIT END -->
