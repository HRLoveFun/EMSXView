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
â”œâ”€â”€ README.md
â”œâ”€â”€ package.json
â”œâ”€â”€ QUICKSTART.md
â”œâ”€â”€ start-services.bat
â”œâ”€â”€ MarketView/
â”‚   â””â”€â”€ README.md
â”œâ”€â”€ ExecutionView/
â”‚   â”œâ”€â”€ README.md
â”‚   â”œâ”€â”€ frontend/
â”‚   â”‚   â”œâ”€â”€ package.json
â”‚   â”‚   â””â”€â”€ src/
â”‚   â”‚       â”œâ”€â”€ App.tsx
â”‚   â”‚       â”œâ”€â”€ sections/
â”‚   â”‚       â”œâ”€â”€ services/
â”‚   â”‚       â”œâ”€â”€ hooks/
â”‚   â”‚       â”œâ”€â”€ stores/
â”‚   â”‚       â”œâ”€â”€ types/
â”‚   â”‚       â””â”€â”€ modules/
â”‚   â”‚           â”œâ”€â”€ marketview/
â”‚   â”‚           â””â”€â”€ costview/
â”‚   â””â”€â”€ backend/
â”‚       â””â”€â”€ api/
â”‚           â”œâ”€â”€ main.py
â”‚           â”œâ”€â”€ config.py
â”‚           â”œâ”€â”€ deps.py
â”‚           â”œâ”€â”€ db.py
â”‚           â”œâ”€â”€ service_provider.py
â”‚           â”œâ”€â”€ routers/
â”‚           â”œâ”€â”€ services/
â”‚           â”œâ”€â”€ repositories/
â”‚           â”œâ”€â”€ models/
â”‚           â”œâ”€â”€ schemas.py
â”‚           â””â”€â”€ tests/
â”œâ”€â”€ CostView/
â”‚   â”œâ”€â”€ README.md
â”‚   â”œâ”€â”€ requirements.txt
â”‚   â”œâ”€â”€ src/
â”‚   â”‚   â”œâ”€â”€ pipeline.py
â”‚   â”‚   â”œâ”€â”€ tca_query_service.py
â”‚   â”‚   â”œâ”€â”€ fill_fetch.py
â”‚   â”‚   â”œâ”€â”€ bdib_fetcher.py
â”‚   â”‚   â”œâ”€â”€ db/                          # Database subsystem (Phase 1-2)
â”‚   â”‚   â”‚   â”œâ”€â”€ __init__.py
â”‚   â”‚   â”‚   â”œâ”€â”€ connection.py            # ConnectionManager + AccessTier
â”‚   â”‚   â”‚   â”œâ”€â”€ protocols.py             # Repository Protocols (12)
â”‚   â”‚   â”‚   â”œâ”€â”€ dto.py                   # Data transfer objects
â”‚   â”‚   â”‚   â”œâ”€â”€ facade.py                # CostViewDatabase unified entry
â”‚   â”‚   â”‚   â”œâ”€â”€ repositories/            # Concrete Repository implementations
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ fills_read.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ fills_write.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ raw_fills_read.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ raw_fills_write.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ market_data_read.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ market_data_write.py
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ integrated.py
â”‚   â”‚   â”‚   â”‚   â””â”€â”€ regime.py
â”‚   â”‚   â”‚   â””â”€â”€ schema/                 # Unified schema management
â”‚   â”‚   â”‚       â”œâ”€â”€ columns.py
â”‚   â”‚   â”‚       â””â”€â”€ migrations/
â”‚   â”‚   â”‚           â””â”€â”€ manager.py       # MigrationManager
â”‚   â”‚   â”œâ”€â”€ raw_fills_db.py              # (deprecated, migrating to db/)
â”‚   â”‚   â”œâ”€â”€ raw_bdib_db.py              # (deprecated, migrating to db/)
â”‚   â”‚   â”œâ”€â”€ fill_bdib_db.py             # (deprecated, migrating to db/)
â”‚   â”‚   â”œâ”€â”€ processed_raw_bdib_db.py    # (deprecated, migrating to db/)
â”‚   â”‚   â”œâ”€â”€ processed_fills_db/         # Package (Facade + sub-repos)
â”‚   â”‚   â””â”€â”€ daily_metrics_calculator.py
â”‚   â”œâ”€â”€ scripts/
â”‚   â”œâ”€â”€ tests/
â”‚   â”œâ”€â”€ data/
â”‚   â””â”€â”€ frontend/
â”‚       â”œâ”€â”€ README.md
â”‚       â””â”€â”€ src/
â”œâ”€â”€ platform_data/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ adapters.py                     # Cross-module adapters
â”‚   â”œâ”€â”€ repositories.py                 # DatabaseView diagnostic queries
â”‚   â””â”€â”€ contracts/                      # Cross-module data contracts
â”‚       â”œâ”€â”€ __init__.py
â”‚       â”œâ”€â”€ fill_contracts.py           # SCORECARD_COHORTS + fill types
â”‚       â”œâ”€â”€ market_data_contracts.py
â”‚       â””â”€â”€ regime_contracts.py
â”œâ”€â”€ docs/
â”‚   â”œâ”€â”€ README.md
â”‚   â”œâ”€â”€ PROJECT_STRUCTURE.md
â”‚   â”œâ”€â”€ DATA_DOMAIN.md
â”‚   â”œâ”€â”€ MEMORY.md
â”‚   â”œâ”€â”€ HANDOFF.md
â”‚   â”œâ”€â”€ EXECUTION_PLATFORM_WBS.md
â”‚   â””â”€â”€ archive/
â”œâ”€â”€ scripts/
â”œâ”€â”€ data/
â”œâ”€â”€ logs/
â”œâ”€â”€ app/               # empty legacy placeholder
â””â”€â”€ config/            # empty legacy placeholder
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

- `modules/marketview/` â€” pre-trade shell anchor
- `sections/` + core app state â€” Execution workspace
- `modules/costview/` â€” active post-trade UI

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

- `routers/` â€” HTTP and WebSocket surfaces by domain
- `services/` â€” business workflows and Bloomberg adapter logic
- `repositories/` â€” operational persistence access
- `models/` / `schemas.py` â€” persistence and API contracts
- `db.py` / `service_provider.py` â€” operational data access boundary

### 4.3 CostView analytical layer

Canonical entries:

- `CostView/src/pipeline.py`
- `CostView/src/tca_query_service.py`
- `CostView/src/db/facade.py` (CostViewDatabase â€” unified DB entry point)

Responsibilities:

- fill ingestion and cleaning
- market data ingestion and transformation
- cross-database TCA queries
- analytical metric assembly and reporting

Database subsystem (`CostView/src/db/`):

- `connection.py` â€” ConnectionManager with AccessTier enforcement across 6 SQLite DBs
- `protocols.py` â€” 12 Repository Protocols (read/write/admin per domain)
- `dto.py` â€” Data transfer objects for cross-layer communication
- `facade.py` â€” CostViewDatabase facade holding all repositories
- `repositories/` â€” 10 concrete repository implementations
- `schema/` â€” Unified column definitions + MigrationManager

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
4. Legacy CostView DB classes (`raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`) are deprecated but still actively used by `pipeline.py` and `MigrationManager`. Full migration to the `db/` subsystem repositories is pending.
5. `platform_data/adapters.py` still imports `RawBDIBDB` directly as a factory default â€” this coupling should be migrated to use `CostViewDatabaseAdapter` or a repository-based factory.

---

## Summary

The current live architecture is not â€œthree separate applications.â€ It is:

- one canonical frontend shell
- three business modules
- one logical data domain with explicit ownership boundaries
- incremental bridges from old surfaces to new ones

This document is the source of truth for repository shape until further structural refactors are completed.
