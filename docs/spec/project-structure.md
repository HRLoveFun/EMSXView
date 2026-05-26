# EMSX Project Structure

> Current architecture reference for the EMSX Trading Platform
> Last updated: 2026-05-07 | Version: 3.2

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
ExecutionView/frontend (canonical shell)
  |- MarketView module anchor
  |- ExecutionView workspace
  `- CostView module
  |
  v
ExecutionView/backend/api (FastAPI assembly layer)
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

- `ExecutionView/frontend/src/App.tsx` is the canonical UI entry point.
- `ExecutionView/backend/api/main.py` is the application assembly entry point, not the sole location of business logic.
- `CostView/src/` is the active analytics and pipeline implementation.
- `platform_data/` is the shared adapter entry for the logical data domain.

---

## 3. Canonical Repository Structure

```text
EMSX/
├── README.md
├── QUICKSTART.md
├── 重启服务.bat
├── MarketView/
│   └── README.md
├── ExecutionView/
│   ├── README.md
│   ├── frontend/
│   │   ├── package.json
│   │   └── src/
│   │       ├── App.tsx
│   │       ├── sections/
│   │       ├── services/
│   │       ├── hooks/
│   │       ├── stores/
│   │       ├── types/
│   │       └── modules/
│   │           ├── marketview/
│   │           └── costview/
│   └── backend/
│       └── api/
│           ├── main.py
│           ├── config.py
│           ├── deps.py
│           ├── db.py
│           ├── service_provider.py
│           ├── routers/
│           ├── services/
│           ├── repositories/
│           ├── models/
│           ├── schemas.py
│           └── tests/
├── CostView/
│   ├── README.md
│   ├── requirements.txt
│   ├── src/
│   │   ├── pipeline.py
│   │   ├── tca_query_service.py
│   │   ├── fill_fetch.py
│   │   ├── bdib_fetcher.py
│   │   ├── db/                          # Database subsystem (Phase 1-2)
│   │   │   ├── __init__.py
│   │   │   ├── connection.py            # ConnectionManager + AccessTier
│   │   │   ├── protocols.py             # Repository Protocols (12)
│   │   │   ├── dto.py                   # Data transfer objects
│   │   │   ├── facade.py                # DatabaseFacade unified entry
│   │   │   ├── repositories/            # Concrete Repository implementations
│   │   │   │   ├── fills_read.py
│   │   │   │   ├── fills_write.py
│   │   │   │   ├── raw_fills_read.py
│   │   │   │   ├── raw_fills_write.py
│   │   │   │   ├── market_data_read.py
│   │   │   │   ├── market_data_write.py
│   │   │   │   ├── integrated.py
│   │   │   │   └── regime.py
│   │   │   └── schema/                 # Unified schema management
│   │   │       ├── columns.py
│   │   │       └── migrations/
│   │   │           └── manager.py       # MigrationManager
│   │   ├── raw_fills_db.py              # (deprecated, use db/ subsystem)
│   │   ├── raw_bdib_db.py              # (deprecated, use db/ subsystem)
│   │   ├── fill_bdib_db.py             # (deprecated, use db/ subsystem)
│   │   ├── processed_raw_bdib_db.py    # (deprecated, use db/ subsystem)
│   │   ├── processed_fills_db/         # Package (Facade + sub-repos)
│   │   └── daily_metrics_calculator.py
│   ├── scripts/
│   ├── tests/
│   ├── data/
│   └── frontend/
│       ├── README.md
│       └── src/
├── platform_data/
│   ├── __init__.py
│   ├── adapters.py                     # Cross-module adapters
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
│   ├── roadmap/wbs.md
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

- `ExecutionView/frontend/src/App.tsx`

Responsibilities:

- owns the platform shell
- mounts MarketView, ExecutionView, and CostView module surfaces
- remains the only authoritative browser entry point

Current module split inside the shell:

- `modules/marketview/` — pre-trade shell anchor
- `sections/` + core app state — Execution workspace
- `modules/costview/` — active post-trade UI

### 4.2 Backend assembly layer

Canonical entry:

- `ExecutionView/backend/api/main.py`

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

- `CostView/src/pipeline.py`
- `CostView/src/tca_query_service.py`
- `CostView/src/db/facade.py` (DatabaseFacade — unified DB entry point)

Responsibilities:

- fill ingestion and cleaning
- market data ingestion and transformation
- cross-database TCA queries
- analytical metric assembly and reporting

Database subsystem (`CostView/src/db/`):

- `connection.py` — ConnectionManager with AccessTier enforcement across 6 SQLite DBs
- `protocols.py` — 12 Repository Protocols (read/write/admin per domain)
- `dto.py` — Data transfer objects for cross-layer communication
- `facade.py` — DatabaseFacade facade holding all repositories
- `repositories/` — 10 concrete repository implementations
- `schema/` — Unified column definitions + MigrationManager

Legacy DB classes (`raw_fills_db.py` etc.) are deprecated and marked for migration.

### 4.4 Shared logical data-domain entry

Canonical entries:

- `platform_data/adapters.py`
- `platform_data/contracts/`
- `platform_data/repositories.py`

Responsibilities:

- exposes a stable adapter layer for platform code
- preserves ownership boundaries between Execution operational data and CostView analytical data
- avoids direct cross-domain deep imports becoming the default integration pattern
- `contracts/` defines the only legal cross-module data types (e.g. `SCORECARD_COHORTS`)
- `CostViewDatabaseAdapter` provides read-only regime/fills/market data queries
- `repositories.py` provides DatabaseView diagnostic query access

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

- `ExecutionView/backend/api/db.py`
- `ExecutionView/backend/api/service_provider.py`
- `platform_data.build_platform_data_access(...).operational`

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

- `CostView/src/tca_query_service.py`
- `CostView/src/pipeline.py`
- `platform_data.build_platform_data_access().analytics`

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

- `CostView/frontend/` is downgraded to legacy prototype status.
- It is not the canonical CostView UI.
- New production UI work should go to `ExecutionView/frontend/src/modules/costview/`.

### 6.2 Empty placeholders

- `app/` is currently empty and non-authoritative.
- `config/` is currently empty and non-authoritative.

These directories should not be treated as active architecture anchors.

### 6.3 Archived documents

- `docs/archive/` stores historical summaries, one-off diagnosis reports, and completed phase checklists.
- Archived documents are kept for audit/reference value, but are not source-of-truth for the current architecture.

---

## 7. Current Alignment Gaps

1. `CostView/frontend/src/` still exists as a legacy code surface and should eventually be archived or removed.
2. ExecutionView operational data and CostView analytical data now have a shared adapter entry; cross-module deep imports from ExecutionView to CostView have been eliminated.
3. MarketView has a shell anchor, but the actual pre-trade workflows and data contracts remain to be built.
4. Legacy CostView DB classes (`raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`) are deprecated (with runtime `DeprecationWarning`) and internally delegate to `ConnectionManager`. Full extraction to a Data Platform subsystem is planned per `docs/spec/data-domain.md`.
5. `platform_data/adapters.py` no longer imports `RawBDIBDB` directly — uses `_ConnectionManagerDailySummaryReader` instead.

---

## Summary

The current live architecture is not “three separate applications.” It is:

- one canonical frontend shell
- three business modules
- one logical data domain with explicit ownership boundaries
- incremental bridges from old surfaces to new ones

This document is the source of truth for repository shape until further structural refactors are completed.
