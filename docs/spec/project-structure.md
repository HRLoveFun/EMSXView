# EMSXView Project Structure

> Current architecture reference for the EMSXView Trading Platform
> Last updated: 2026-07-02 | Version: 3.3（版本号对齐 [data-domain.md](data-domain.md) v3.3；本版本仅刷新头部版本号/日期，结构章节保持稳定）

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
| MarketView | Pre-trade analysis, market context, execution preparation | Shell anchor exists, domain capabilities still to be built |
| ExecutionView | Real-time order and route management via Bloomberg EMSX | Production-ready core |
| CostView | Post-trade analytics, TCA, data pipeline, reporting | Active data/analytics module with shell-integrated UI |

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
  |- schemas.py
  `- db.py / service_provider.py
  |
  +--> Bloomberg EMSX API (operational execution data)
  `--> CostView/src (analytical queries + pipeline data)
```

Key runtime truth:

- `frontend/src/App.tsx` is the canonical UI entry point.
- `backend/api/main.py` is the application assembly entry point, not the sole location of business logic.
- `CostView/src/` is the active analytics and pipeline implementation.
- `platform_data/` is the shared adapter entry for the logical data domain.

---

## 3. Canonical Repository Structure

```text
EMSXView/
├── README.md
├── QUICKSTART.md
├── 重启服务.bat
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
│       │   ├── costview/             # CostView module
│       │   └── databaseview/         # DatabaseView module
│       └── shared/                   # Cross-module shared layer
├── backend/
│   └── api/
│       ├── main.py                   # FastAPI application entry (:3000)
│       ├── config.py
│       ├── deps.py
│       ├── db.py
│       ├── service_provider.py
│       ├── routers/
│       ├── services/
│       ├── repositories/
│       ├── models/
│       ├── schemas/
│       └── tests/
├── MarketView/
│   └── README.md
├── CostView/
│   ├── README.md
│   ├── requirements.txt
│   ├── src/
│   │   ├── pipeline.py
│   │   ├── tca_query_service.py
│   │   ├── fill_fetch.py
│   │   ├── bdib_fetcher.py
│   │   ├── daily_metrics_calculator.py
│   │   └── (legacy raw_*_db.py / fill_bdib_db.py / processed_raw_bdib_db.py — DELETED)
│   ├── scripts/
│   ├── tests/
│   ├── data/
│   └── frontend/
│       ├── README.md
│       └── src/
├── platform_data/
│   ├── __init__.py
│   ├── adapters/                      # Cross-module adapters (subpackage)
│   │   ├── __init__.py                # Backward-compat re-export entry point
│   │   ├── handoff.py                 # HandoffExchangeAdapter
│   │   ├── redis_handoff.py           # RedisHandoffExchangeAdapter
│   │   ├── market.py                  # MarketReferenceDataAdapter
│   │   └── tca_bridge.py              # TCA service DI + daily summary reader
│   ├── repositories.py                 # DatabaseView diagnostic queries
│   └── contracts/                      # Cross-module data contracts
│       ├── __init__.py
│       ├── fill_contracts.py           # SCORECARD_COHORTS + fill types
│       ├── market_data_contracts.py
│       └── regime_contracts.py
├── docs/
│   ├── index.md
│   ├── dev-guide.md
│   ├── handoff.md
│   ├── spec/
│   │   ├── project-structure.md
│   │   ├── data-domain.md
│   │   └── memory.md
│   └── archive/
├── scripts/
├── data/
├── logs/
├── app/               # empty legacy placeholder
└── config/            # empty legacy placeholder
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
- `modules/execution/` — Execution workspace
- `modules/costview/` — active post-trade UI
- `modules/databaseview/` — database admin UI

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
- `models/` / `schemas.py` — persistence and API contracts
- `db.py` / `service_provider.py` — operational data access boundary

### 4.3 CostView analytical layer

Canonical entries:

- `CostView/src/tca_query_service.py`
- `DataPipeline/storage/facade.py` (DatabaseFacade — unified DB entry point)

Responsibilities:

- fill ingestion and cleaning
- market data ingestion and transformation
- cross-database TCA queries
- analytical metric assembly and reporting

Database subsystem (`DataPipeline/storage/`):

- `connection.py` — ConnectionManager with AccessTier enforcement across 6 SQLite DBs
- `facade.py` — DatabaseFacade facade holding all repositories
- `dto.py` — Data transfer objects for cross-layer communication
- `repositories/` — concrete repository implementations (fills, raw_fills, market_data, integrated, regime, fetch_history)
- `schema/` — Unified column definitions + MigrationManager

Legacy DB classes (`raw_fills_db.py` etc.) have been **deleted** — migrated to `DataPipeline/storage/` repositories.

### 4.4 Shared logical data-domain entry

Canonical entries:

- `platform_data/adapters/`
- `platform_data/contracts/`
- `platform_data/repositories.py`

Responsibilities:

- exposes a stable adapter layer for platform code
- preserves ownership boundaries between Execution operational data and CostView analytical data
- avoids direct cross-domain deep imports becoming the default integration pattern
- `contracts/` defines the only legal cross-module data types (e.g. `SCORECARD_COHORTS`)
- `adapters/tca_bridge.py` 的 `get_tca_query_service()` 提供 TCA / scorecard 查询（读取 `tca_route_summary` 汇总表）
- `execution_history_service.py` 提供执行历史读取路径
- `repositories.py` provides DatabaseView diagnostic query access
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
3. MarketView has a shell anchor, but the actual pre-trade workflows and data contracts remain to be built. MarketView runs as a standalone service on :8001.
4. Legacy CostView DB classes (`raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`) have been **deleted** — fully migrated to `DataPipeline/storage/` repositories per `docs/spec/data-domain.md`.
5. `platform_data/adapters.py` has been split into `platform_data/adapters/` subpackage (with backward-compat re-exports in `__init__.py`).

---

## Summary

The current live architecture is not “three separate applications.” It is:

- one canonical frontend shell
- three business modules
- one logical data domain with explicit ownership boundaries
- incremental bridges from old surfaces to new ones

This document is the source of truth for repository shape until further structural refactors are completed.
