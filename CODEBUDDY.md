# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## Project Overview

EMSX (Execution Management System eXtended) is a Bloomberg EMSX-integrated trading platform covering pre-trade analysis, order execution, and post-trade TCA analytics. It is a monorepo with three business modules sharing a single React frontend shell and a Python data pipeline.

## Build & Run Commands

### Frontend (ExecutionView/frontend)

```bash
cd ExecutionView/frontend
npm install          # Install dependencies
npm run dev          # Dev server on :5173 (mock mode if VITE_API_URL is empty)
npm run build        # tsc -b && vite build → dist/
npm run lint         # ESLint
npm test             # vitest run
npm run test:watch   # vitest watch
```

- Vite proxies `/api/*` and `/ws/*` to `http://localhost:3000` in dev mode.
- `VITE_USE_MOCK=true` enables mock Bloomberg data when no backend is running.

### Backend (ExecutionView/backend/api)

```bash
cd ExecutionView/backend/api
pip install -r requirements.txt
python main.py                   # Starts uvicorn on :3000
uvicorn main:app --port 3000     # Alternative
pytest                           # Run backend tests
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
cd ExecutionView/backend
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

All module UIs are mounted in the **single** ExecutionView/frontend React shell — MarketView and CostView do not have standalone production UIs.

### Frontend — Shell + Lazy-Loaded Modules

- **AppShell** (`src/app/AppShell.tsx`) — root layout orchestrator with toolbar, module tabs, and toast container
- Four lazy-loaded React modules under `src/modules/`:
  - `execution/` — order tables, route tables, monitoring, batch operations
  - `costview/` — post-trade TCA UI (canonical)
  - `marketview/` — pre-trade market snapshot (shell anchor)
  - `databaseview/` — database admin/diagnostics
- Vite manual chunking ensures each module gets its own bundle (`module-costview`, `module-marketview`, etc.)
- Shared code lives in `src/shared/` (hooks, lib, services, types) and `src/components/` (React components)
- API client services in `src/services/`

**Path aliases** (configured in both vite.config.ts and tsconfig.app.json):
- `@/*` → `./src/*`
- `@app/*` → `./src/app/*`
- `@shared/*` → `./src/shared/*`
- `@execution/*` → `./src/modules/execution/*`
- `@costview/*` → `./src/modules/costview/*`
- `@marketview/*` → `./src/modules/marketview/*`
- `@databaseview/*` → `./src/modules/databaseview/*`

### Backend — Layered FastAPI

```
Routers (HTTP/WebSocket) → Services (business logic) → Repositories (data access) → Models (persistence)
```

- Entry point: `ExecutionView/backend/api/main.py`
- **Core routers** (always loaded): connection, auth, orders, routes, broker, marketview, realtime, debug, route_plans, market_broker_mapping
- **Optional routers** (graceful fallback): costview, database, execution_history — if import fails, core ExecutionView still starts
- Key services: `BloombergEMSXService` (Bloomberg API adapter), `AuthService`, `RouteService`, `ComplianceService`
- `RepositoryProvider` gates DB reads/writes behind `ENABLE_DB_PERSISTENCE` flag
- Bloomberg connection starts as an async background task (can take 30-120s for BPIPE initialization)

### DataPipeline — Stage-Based Processing

`DataPipeline/orchestration/` runs a multi-stage pipeline:

1. **Ingestion** (`stages_ingest.py`): Fetch fills from Bloomberg EMSX, ingest raw fills
2. **Processing** (`stages_process.py`): Clean, aggregate, integrate with BDIB (intraday bars), compute daily metrics
3. **Analysis** (`stages_analysis.py`): TCA, regime detection, attribution

Data flows through SQLite databases: `raw_fills.db` → `processed_fills.db` → `fill_bdib.db` → `bdib_daily_summary`

All pipeline configuration is centralized in `DataPipeline/config.py` (Config class with DB paths, table names, date formats). Data directory is configurable via `EMSX_DATA_DIR` env var, defaulting to `CostView/data`.

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

- Frontend uses **shadcn/ui** components (Radix UI + Tailwind CSS). New UI components should follow the same pattern — use `npx shadcn@latest add <component>` to add new shadcn components.
- TypeScript strict mode is enabled (`noUnusedLocals`, `noUnusedParameters`, `erasableSyntaxOnly`).
- Backend uses Pydantic v2 models for schemas; all API responses wrapped in `ApiResponse`.
- The Bloomberg Terminal must be running locally (or accessible via `BLOOMBERG_HOST`) for live trading features. Without it, use mock mode.
- Pipeline config is the single source of truth — do not hardcode DB paths or table names; import from `DataPipeline.config.Config`.
- Backend optional routers must never break the core ExecutionView — use the `_register_optional` pattern in `main.py`.
