# Architecture Decisions

Key architectural decisions for the EMSX project. Update when structural commitments change.

## AD-01: Monorepo with module-level separation

**Decision:** The project is organized as a monorepo with top-level modules (ExecutionView, CostView, MarketView, DataPipeline) sharing a single React frontend shell.  
**Rationale:** Each module represents a distinct phase of the trade lifecycle (pre-trade, execution, post-trade). Shared code lives in `platform_data/` adapters and `DataPipeline/` package.  
**Consequence:** Module boundaries are enforced at the directory level. Cross-module access must go through `platform_data/` adapters, never direct imports.

## AD-02: Single React shell with lazy-loaded modules

**Decision:** All module UIs mount into `frontend/` via lazy-loaded React components. CostView and MarketView do not run standalone frontends.  
**Rationale:** Unified user experience for traders who need to navigate between pre-trade, execution, and post-trade views.  
**Consequence:** Vite manual chunking ensures each module gets its own bundle. Path aliases (`@execution/*`, `@costview/*`) isolate module boundaries.

## AD-03: Backend optional routers with graceful fallback

**Decision:** CostView, DatabaseView, and ExecutionHistory routers register via `_register_optional()` in `main.py`. If any fail to import, core ExecutionView still starts.  
**Rationale:** The execution platform is mission-critical. Post-trade analytics and database admin are value-add features that should not block order routing.  
**Consequence:** New optional routers must follow this pattern. Core routers (orders, routes, broker, auth) are loaded unconditionally.

## AD-04: DataPipeline as independent package with centralized config

**Decision:** All pipeline configuration lives in `DataPipeline/config.py` (Config class). Data directory is configurable via `EMSX_DATA_DIR` env var, defaulting to `CostView/data` for backward compatibility.  
**Rationale:** Avoids duplication of DB paths, table names, and date formats. Enables relocation of SQLite files without code changes.  
**Consequence:** Do not hardcode DB paths or table names — always import from `DataPipeline.config.Config`.

## AD-05: RepositoryProvider gates DB persistence

**Decision:** Backend database access is gated behind `RepositoryProvider` with `ENABLE_DB_PERSISTENCE` flag. When disabled, in-memory fallbacks are used.  
**Rationale:** Operational flexibility — the execution platform can run with or without PostgreSQL, supporting both ephemeral and persistent deployments.  
**Consequence:** All new data access must go through repository providers, not direct SQLAlchemy/asyncpg calls.

## AD-06: Bloomberg connection as async background task

**Decision:** Bloomberg EMSX session initialization runs as a background `asyncio.create_task()` during FastAPI lifespan startup.  
**Rationale:** B-PIPE session.start() + openService() can take 30-120s. The HTTP server must be ready to accept requests immediately while Bloomberg connects.  
**Consequence:** Frontend must handle the warmup UX gracefully (startup status endpoint). Request handling must tolerate Bloomberg being temporarily unavailable.

## AD-07: SQLite for pipeline data, PostgreSQL for operational state

**Decision:** The DataPipeline uses SQLite for analytical and pipeline data (fills, BDIB bars, metrics). Backend operational state (orders, routes, route plans) can optionally persist to PostgreSQL.  
**Rationale:** SQLite is simpler for pipeline batch workloads. PostgreSQL provides durability and concurrency for live trading state.  
**Consequence:** Two separate connection management patterns: ConnectionManager for SQLite, async SQLAlchemy for PostgreSQL.

## AD-08: platform_data adapters as cross-domain bridge

**Decision:** Cross-module data access goes through `platform_data/adapters.py`, not direct imports between modules.  
**Rationale:** Prevents tight coupling between ExecutionView, CostView, and MarketView. Adapters can evolve independently of internal implementations.  
**Consequence:** New cross-module queries must be exposed through adapters. Direct imports across module boundaries are prohibited.
