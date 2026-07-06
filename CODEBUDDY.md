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

> **📦 已归档（2026-07-02）** — 数据管理重构 Phase A-D（15/15 任务）已全部完成，.BAK 安全网已清理（释放 57.58 GB），归档提交 `3b00236 docs: 归档重构工作流并更新业务流程文档`。
>
> 后续涉及数据/存储/管道层的代码改动：
> - **运行时参数**（`BDIB_PARQUET_ENABLED` / `BDIB_QUERY_ENGINE` / `PARTITION_DUAL_WRITE` / `PARTITION_READ_NEW` / `PROCESSED_RAW_BDIB_ENABLED` / 各类保留月数）请查阅 [data_management_refactoring_control.md §二 可调参数](data_management_refactoring_control.md#二可调参数)
> - **历史方案与安全机制设计**查阅 [`data_management_refactoring_plan.md`](data_management_refactoring_plan.md)（📦 归档态，不接受新执行指令）
> - **运行时健康度**由 [`scripts/health_check.py`](scripts/health_check.py) 监控（DB 体积 / WAL / TCA 延迟 / 完整性）

<!-- SPECKIT START -->
## Current Plan

**Status**: ✅ 护栏机制已落地（2026-06-25）；S2 跨日维度修复已完成（2026-07-03，验证 `processed_fills` 与 `raw_fills` 非 DFD gap=0）

**Feature**: 数据管道护栏机制 + S2 跨日维度修复
**Branch**: `datapipeline-checking`（基于 `001-architecture-module-completion`）
**Plan**: `specs/002-pipeline-guardrail/plan.md`
**Spec**: `specs/002-pipeline-guardrail/spec.md`

Key artifacts:
- `specs/002-pipeline-guardrail/research.md` — 熔断器模式、Pydantic 校验、基线测试、契约检查、日志方案研究
- `specs/002-pipeline-guardrail/data-model.md` — PipelineRun、StageExecution、ValidationViolation、CircuitBreakerState、PipelineSchema 实体定义
- `specs/002-pipeline-guardrail/contracts/guard-pipeline-api.md` — GuardPipeline、Validator、CircuitBreaker、PipelineRunLogger API 契约
- `specs/002-pipeline-guardrail/quickstart.md` — 10 个验证场景，覆盖校验/熔断/完整性/契约/日志
- `DataPipeline/tests/guardrail/test_data_quality.py` — 单元/集成/回归测试：Exchange 空值/未知报错、S2 日期一致性、agg_fills_10s route_registry 列补全、零股 VWAP 过滤、S2 跨日维度回归（3 个 case，2026-07-03 新增）

### S2 跨日维度修复记录（2026-07-03）

- **问题**：`ProcessRawFillsStage` 历史上以 `source_date`（拉取日）作 `target_dates` 维度。一个 `source_date` 内的成交可能跨多个真实交易日（`order_as_of_date`），S2 写入前校验 `order_as_of_date` 与输入日期一致时，整批拒绝。13 个 `source_date` 共 3,600,000+ 行未生成 `processed_fills`/`agg_fills`/`route_registry`/`fill_bdib`。
- **修复**：`target_dates` 维度从 `source_date` 改为 `raw_fills` 的 `DISTINCT order_as_of_date`，与 `processed_fills.order_as_of_date` 真实交易日语义保持一致。
- **改动**：`orchestration/stages_ingest.py` + `storage/repositories/raw_fills.py`（新增 `get_distinct_order_as_of_dates()` + `get_fills_for_date()` 接受 `YYYYMMDD`）；新增回归测试 `TestStage2CrossDayProcessing`。
- **回填脚本**：`scripts/ops/reprocess_affected_dates.py --missing-source-dates --no-s5`，对 13 个缺失 `source_date` 展开为 69 个 OAD 重新跑 S2/S3/S4。`raw_fills` 非 DFD 11,112,677 = `processed_fills` 11,112,677，gap=0。
- **配套运维**：`scripts/ops/cleanup_processed_fills_mismatches.py`（孤儿/日期不匹配/无效 `order_as_of_date` 行清理，--dry-run、--dates、自动备份）+ `scripts/ops/analyze_processed_fills_nulls.py`（每列 NULL/空字符串统计）。
- **新增配置**：`STRICT_MISSING_TICKER_VALIDATION`（默认 `false`，启用时 `process_fills` 阶段 Exchange/equ_ticker 缺失直接抛 `ValueError`）。
<!-- SPECKIT END -->
