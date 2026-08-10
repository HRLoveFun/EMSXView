# EMSXView — AI Coding Agent Guide

This file provides guidance to AI coding agents (CodeBuddy, Claude Code, Copilot, Cursor, etc.) when working in this repository.

> **同步机制**：本文件与 `AGENTS.md` 内容完全相同，由 git pre-commit hook 自动同步。编辑任一文件后提交，另一文件自动同步。规范源为 `CODEBUDDY.md`。

## 文档阅读顺序（必读）

进入本仓库的 AI agent **必须**按以下顺序阅读文档，再开始任何代码改动：

1. `CODEBUDDY.md` / `AGENTS.md`（本文件）— 工作流与安全规则
2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理
4. `.codebuddy/rules/module-boundary.md` — ★ 模块边界契约
5. `docs/spec/project-structure.md` — 当前仓库结构
6. `docs/spec/data-domain.md` — 数据域所有权
7. `docs/spec/memory.md` — 架构记忆入口（指向 ADR 列表）
8. `docs/spec/module-onboarding.md` — 新增模块流程
9. `docs/spec/anti-patterns.md` — ★ 禁止模式

> **📦 已归档（2026-07-02）** — 数据管理重构 Phase A-D（15/15 任务）已全部完成，.BAK 安全网已清理（释放 57.58 GB）。以下两文件仅作历史记录保留，不再作为活跃必读：
> - ~~`data_management_refactoring_control.md` — 重构进度~~ → 运行时参数（`BDIB_PARQUET_ENABLED` / `BDIB_QUERY_ENGINE` / `PARTITION_DUAL_WRITE` / `PARTITION_READ_NEW` / `PROCESSED_RAW_BDIB_ENABLED` / 保留月数）改向 [control.md §二 可调参数](data_management_refactoring_control.md#二可调参数)
> - ~~`data_management_refactoring_plan.md` — 重构实施~~ → 历史方案与安全机制设计的查阅入口（不接受新执行指令）

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

CostView 独立服务包含 `costview`（TCA 查询）和 `monitoring`（BDIB 健康度、指标覆盖率、报告聚合）两个路由器。

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

S3 阶段额外预计算 `tca_route_summary` 路由汇总表（`DataPipeline/processing/tca_route_metrics.py`），将路由层级 TCA 指标（VWAP 偏离、实现价差、fill_count 等）从订单层级实时计算改为管道批处理预计算，CostView 查询直接读取汇总表。

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
- TCA 路由层级指标从 `tca_route_summary` 预计算表读取，禁止在查询时实时聚合。
- CostView 监控数据通过 `monitoring` 路由器提供，逻辑封装在 `CostView/src/monitoring/` 模块。

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

**Status**: ✅ 护栏机制已落地（2026-06-25）；S2 跨日维度修复已完成（2026-07-03）；BDIB 覆盖率修复已完成（2026-07-08）；TCA 路由汇总表重构已完成（2026-07-16）；TCA 监控与报告生成已完成（2026-08-06）

**Feature**: 数据管道护栏机制 + S2 跨日维度修复 + TCA 路由汇总 + 监控报告
**Branch**: `datapipeline-checking`（基于 `001-architecture-module-completion`）
**Plan**: `specs/002-pipeline-guardrail/plan.md`
**Spec**: `specs/002-pipeline-guardrail/spec.md`

Key artifacts:
- `specs/002-pipeline-guardrail/research.md` — 熔断器模式、Pydantic 校验、基线测试、契约检查、日志方案研究
- `specs/002-pipeline-guardrail/data-model.md` — PipelineRun、StageExecution、ValidationViolation、CircuitBreakerState、PipelineSchema 实体定义
- `specs/002-pipeline-guardrail/contracts/guard-pipeline-api.md` — GuardPipeline、Validator、CircuitBreaker、PipelineRunLogger API 契约
- `specs/002-pipeline-guardrail/quickstart.md` — 10 个验证场景，覆盖校验/熔断/完整性/契约/日志
- `DataPipeline/tests/guardrail/test_data_quality.py` — 单元/集成/回归测试：Exchange 空值/未知报错、S2 日期一致性、agg_fills_10s route_registry 列补全、零股 VWAP 过滤、S2 跨日维度回归（3 个 case，2026-07-03 新增）
- `DataPipeline/processing/tca_route_metrics.py` — TCA 路由汇总表预计算（VWAP 偏离、实现价差、fill_count 等指标）
- `DataPipeline/tests/processing/test_tca_route_metrics.py` — 路由汇总表计算单元/集成测试
- `CostView/src/monitoring/` — 监控模块（`bdib_health.py` BDIB 健康度、`metric_coverage.py` 指标覆盖率、`report_aggregator.py` 报告聚合器、`time_range.py` 时间范围工具）
- `CostView/api/routers/monitoring.py` — 监控 API 路由器
- `CostView/tests/test_monitoring.py` — 监控模块单元/集成测试
- `scripts/reports/generate_tca_report.py` — TCA HTML 报告生成 CLI（支持时间范围和指标过滤）
- `scripts/reports/tca_report_html.py` — HTML 报告渲染器（内联 CSS + 服务端生成 SVG 图表，零外部依赖）
- `docs/textbook/Algo_TCA.md` — TCA 算法教科书（840 行，涵盖 VWAP 偏离、实现价差、regime 检测等）

### S2 跨日维度修复记录（2026-07-03）

- **问题**：`ProcessRawFillsStage` 历史上以 `source_date`（拉取日）作 `target_dates` 维度。一个 `source_date` 内的成交可能跨多个真实交易日（`order_as_of_date`），S2 写入前校验 `order_as_of_date` 与输入日期一致时，整批拒绝。13 个 `source_date` 共 3,600,000+ 行未生成 `processed_fills`/`agg_fills`/`route_registry`/`fill_bdib`。
- **修复**：`target_dates` 维度从 `source_date` 改为 `raw_fills` 的 `DISTINCT order_as_of_date`，与 `processed_fills.order_as_of_date` 真实交易日语义保持一致。
- **改动**：`orchestration/stages_ingest.py` + `storage/repositories/raw_fills.py`（新增 `get_distinct_order_as_of_dates()` + `get_fills_for_date()` 接受 `YYYYMMDD`）；新增回归测试 `TestStage2CrossDayProcessing`。
- **回填脚本**：`scripts/ops/reprocess_affected_dates.py --missing-source-dates --no-s5`，对 13 个缺失 `source_date` 展开为 69 个 OAD 重新跑 S2/S3/S4。`raw_fills` 非 DFD 11,112,677 = `processed_fills` 11,112,677，gap=0。
- **配套运维**：`scripts/ops/cleanup_processed_fills_mismatches.py`（孤儿/日期不匹配/无效 `order_as_of_date` 行清理，--dry-run、--dates、自动备份）+ `scripts/ops/analyze_processed_fills_nulls.py`（每列 NULL/空字符串统计）。
- **新增配置**：`STRICT_MISSING_TICKER_VALIDATION`（默认 `false`，启用时 `process_fills` 阶段 Exchange/equ_ticker 缺失直接抛 `ValueError`）。

### BDIB 覆盖率修复记录（2026-07-08）

- **问题**：549 个 ticker 有成交但无 BDIB 行情。根因：① `BDIB_EXCHANGE` 白名单遗漏 9 个交易所（424 个 ticker）；② 108 个 ticker 未注册到 `ticker_repository`；③ 17 个 ticker Bloomberg BDIB API 返回空。
- **修复**：`Config.BDIB_EXCHANGE` 从 24 扩展至 33 个交易所（+HK/CN/BZ/MM/PW/DC/IT/NZ/MUMBAI）；`exchange_tz.py` NZ 时区修正 `Australia/Sydney` → `Australia/Auckland`；补注册 108 个 ticker；新增 `BDIBCoverageGuard`（S5 前置校验）。
- **运维脚本**：`scripts/ops/backfill_ticker_repository.py`（ticker 补注册）、`scripts/ops/investigate_bdib_api_failures.py`（17 个 API 失败排查）、`scripts/ops/backfill_bdib_by_market.py`（按市场分批 BDIB 回补）。
- **执行记录**（2026-07-08）：BDIB 数据回补已完成——9 个新市场共 1,012 天成功、65,638,213 行写入、0 天失败（耗时 3.8 小时）。MUMBAI 市场 1 个 ticker 已标记 outdated。8 个 API 失败 ticker 已标记 outdated（BDIB 确认无数据）。8 个原 API 失败 ticker 经复查确认 API 正常（可正常拉取）。
- **BDIB 保留窗口限制**：Bloomberg BDIB (intraday bar) API 对历史数据有保留期限——US/LN/JP/KS 等主要市场约 9 个月，HK/NZ/CN/BZ 等市场约 6 个月。超出保留窗口的日期返回空数据，无法回补。`backfill_bdib_by_market.py` 默认 `--start` 动态计算为 `today - 180 天`（`Config.BDIB_API_RETENTION_DAYS`），确保所有市场都在保留窗口内。

### TCA 路由汇总表重构记录（2026-07-16）

- **问题**：CostView TCA 查询在请求时从订单层级实时聚合路由指标（VWAP 偏离、实现价差等），大数据量下查询延迟高。
- **修复**：新增 `tca_route_summary` 预计算表，管道 S3 阶段批量计算路由层级 TCA 指标并持久化。CostView 查询直接读取汇总表，消除实时聚合开销。
- **改动**：
  - `DataPipeline/processing/tca_route_metrics.py`（新增 408 行）— 路由汇总表计算逻辑
  - `DataPipeline/orchestration/stages_process.py` — 新增路由汇总表计算 stage
  - `DataPipeline/storage/schema/columns.py` + `inline_ddl.py` — `tca_route_summary` 表 DDL
  - `CostView/src/tca_query_builder.py`（新增）— TCA 查询构建器，读取汇总表
  - `CostView/src/tca_query_service.py` — 重构为使用汇总表查询
  - `platform_data/contracts/tca_contracts.py` — 更新 TCA 契约定义
  - 前端移除 `TcaRouteTable.tsx`，重构 `AnalysisView`/`OverviewView`/`TcaOrderTable`
- **fill_count 指标**（2026-07-17 新增）：`tca_route_summary` 表新增 `fill_count` 列，统计每条路由的成交笔数。
- **配套脚本**：`scripts/recompute_route_metrics.py`（路由汇总表重算）、`scripts/check_trs.py`（汇总表完整性检查）、`scripts/monitor_trs.py`（汇总表监控）、`scripts/ops/cleanup_excluded_exchanges_tickers.py`（清理排除交易所的 ticker 数据）。
- **测试**：`DataPipeline/tests/processing/test_tca_route_metrics.py` — 路由汇总表计算单元/集成测试。

### TCA 监控与报告生成记录（2026-08-06）

- **新增监控模块**（`CostView/src/monitoring/`）：
  - `bdib_health.py` — BDIB 数据健康度检查（覆盖率、缺失日期、ticker 状态）
  - `metric_coverage.py` — TCA 指标覆盖率统计（按交易所/日期维度）
  - `report_aggregator.py` — 报告聚合器（汇总多维度监控数据）
  - `time_range.py` — 时间范围工具（支持日/周/月/季度/自定义区间）
- **新增 API 路由器**：`CostView/api/routers/monitoring.py`（193 行）— 监控数据查询接口
- **新增前端组件**：
  - `MonitoringView.tsx`（296 行）— 监控主视图，含 BDIB 健康度、指标覆盖率看板
  - `CoverageHeatmap.tsx`（112 行）— 覆盖率热力图
  - `ReportView.tsx`（286 行）— 报告视图
  - `lib/monitoring-metrics.ts` — 前端监控指标常量（与后端白名单对齐）
- **TCA HTML 报告生成**（`scripts/reports/`）：
  - `generate_tca_report.py`（164 行）— CLI 工具，支持时间范围和指标过滤
  - `tca_report_html.py`（442 行）— HTML 渲染器，内联 CSS + 服务端生成 SVG 图表，零外部依赖
- **测试**：`CostView/tests/test_monitoring.py`（469 行）、`frontend/src/modules/costview/__tests__/monitoring-view.test.tsx`（194 行）
- **文档**：`docs/textbook/Algo_TCA.md`（840 行）— TCA 算法教科书
- **清理**：移除临时文件 `generate_ks_bdib_stats.py`、`recompute_*.err`、`tca_plan.md`、`tca_route_summary_null_investigation.md`
<!-- SPECKIT END -->
