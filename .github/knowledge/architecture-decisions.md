# Architecture Decisions Log

> Auto-maintained by the iterative update mechanism. Records architectural decisions, their context, and review schedule.

---

## Decision: Single-File Backend (main.py) [Superseded]

- **Date**: 2026-03 (initial design)
- **Context**: Fast iteration during early development; Bloomberg blpapi requires specific session lifecycle management; all EMSX operations are tightly coupled
- **Decision**: Keep all backend logic in a single `main.py` file (~3695 lines) with FastAPI + blpapi
- **Consequences**: Easy to search and understand data flow; difficult to test in isolation; merge conflicts likely with multiple contributors; IDE performance degrades
- **Technical Debt**: HIGH â€” file exceeds 3000-line threshold; contains models, routes, Bloomberg session management, and business logic in one file
- **Review Date**: 2026-04-16 (next major feature)
- **Status**: Superseded on 2026-04-03 by router/service/schema extraction. `Execution/backend/api/main.py` now acts primarily as the application assembly entry point while business logic lives in routers, services, repositories, and schemas.

---

## Decision: No Redux â€” React Hooks + Context

- **Date**: 2026-03 (initial design)
- **Context**: Application state is primarily server-driven (Bloomberg subscriptions); limited client-side state complexity
- **Decision**: Use React hooks and context providers instead of Redux/Zustand
- **Consequences**: Simpler mental model; fewer dependencies; may need refactoring if client-side state grows (e.g., complex filters, user preferences)
- **Review Date**: 2026-05-01

---

## Decision: Bloomberg Field Subscription Strategy

- **Date**: 2026-03
- **Context**: Bloomberg EMSX API only sends fields that are explicitly subscribed; subscribing to all fields wastes bandwidth and may cause rate limiting
- **Decision**: Subscribe to 20 active fields; removed EMSX_CURRENCY (confirmed invalid by Bloomberg)
- **Consequences**: Must manually add fields to subscription when new data is needed; risk of silent data absence if field is missing from subscription list
- **Review Date**: Ongoing (each time a new field is needed)

---

## Decision: Separate Databases for CostView Pipeline

- **Date**: 2026-03
- **Context**: Raw fills come from Excel/Bloomberg in various formats; processed data needs consistent schema for aggregation
- **Decision**: Two SQLite databases â€” `raw_fills.db` (TEXT columns for schema flexibility) and `processed_fills.db` (typed columns + aggregations + labels)
- **Consequences**: Clear separation of concerns; raw data preserved for reprocessing; extra storage overhead; must maintain two schemas
- **Review Date**: 2026-06-01

---

## Decision: Docker Compose for Production Deployment

- **Date**: 2026-03
- **Context**: Need to package backend + frontend + Redis + monitoring as a single deployable unit
- **Decision**: Docker Compose with multi-stage builds, Nginx reverse proxy, optional Prometheus/Grafana monitoring profile
- **Consequences**: Easy single-command deployment; Bloomberg connectivity requires `host.docker.internal`; monitoring optional via `--profile monitoring`
- **Review Date**: 2026-06-01

---

## Decision: Workflow-Ledger Governance for Execution Platform Delivery

- **Date**: 2026-04-02
- **Context**: The execution-platform roadmap spans multiple phases, repositories, and automation layers; session-to-session continuity and machine-readable progress tracking are required before large refactors begin.
- **Decision**: Use `docs/roadmap/wbs.md` as the human-readable source plan and `.workbuddy/plans/execution-platform-status.yaml` + `.workbuddy/plans/execution-platform-risk-register.yaml` as the authoritative machine-readable delivery ledger for sprint state, issue dependencies, checkpoints, and risks.
- **Consequences**: Delivery state becomes auditable and automation-friendly; issue/PR workflows can enforce sprint metadata; some duplication now exists between narrative plan docs and machine-readable ledgers and must be kept synchronized.
- **Review Date**: 2026-05-01

---

## Decision: CostView Pipeline Parallelization with Per-Thread DB Connections

- **Date**: 2026-04-15
- **Context**: CostView 6-stage pipeline processed dates serially in S2/S3 and tickers serially in S5. SQLite WAL mode supports concurrent readers + single writer.
- **Decision**: Add ThreadPoolExecutor-based parallelism with per-thread DB connections (max 4 dates, max 3 tickers). Falls back to serial when max_workersâ‰¤1. Configurable via `MAX_PARALLEL_DATES` and `MAX_PARALLEL_TICKERS` in `processing_config.py`.
- **Consequences**: Expected 2-4x speedup on multi-date runs; each thread creates its own RawFillsDB/ProcessedFillsDB instance avoiding connection sharing; requires Phase 1.2 transaction atomicity (optional `conn` param on write methods) to be in place first.
- **Review Date**: 2026-06-01

---

## Decision: Vectorized Timezone Conversion via batch_convert_ny_to_local

- **Date**: 2026-04-15
- **Context**: `derive_exchange_times()` used per-row `iterrows()` + `convert_ny_to_local()` â€” O(N) ZoneInfo lookups. For 100k fills, this was the single largest bottleneck.
- **Decision**: Group rows by exchange code (5-15 groups per day), do one `ZoneInfo` lookup per group, then use vectorized `pd.Series.dt.tz_convert()`. New `batch_convert_ny_to_local()` in `exchange_tz.py`.
- **Consequences**: 10-50x expected speedup; same output format; falls back to NY timezone for unrecognized exchange codes.
- **Review Date**: 2026-06-01

---

## Decision: Lazy-Loaded CostView Module Inside Execution Frontend Shell

- **Date**: 2026-04-21
- **Context**: CostView analysis UI needed to be added to the existing `Execution/frontend` application without introducing a router rewrite, role-based entry differences, or URL-shared state. The user also required configurable alert thresholds plus CSV/Excel/PDF export from the same shell.
- **Decision**: Integrate CostView as a lazy-loaded top-level module inside `Execution/frontend/src/App.tsx`, keep the existing monitor/execution/settings tabs under the Execution workspace, and persist CostView filters/config/export defaults in browser localStorage. Implement Excel export without an external runtime dependency by generating an Excel-compatible multi-sheet XML workbook.
- **Consequences**: Incremental integration avoids destabilizing the current execution workflow and keeps bundle impact isolated behind lazy loading; CostView state remains browser-local and not shareable by URL; the new CostView chunk is still sizable and may need further code splitting if the module expands.
- **Review Date**: 2026-05-15

---

## Decision: Single Frontend Shell with Three Business Modules and One Logical Data Domain

- **Date**: 2026-04-22
- **Context**: The repository evolved faster than the top-level architecture docs. In practice, `Execution/frontend` had already become the active platform shell, CostView had been integrated into that shell, MarketView still existed as a domain placeholder, and data responsibilities were split between Execution operational persistence and CostView analytical storage. The target architecture needed to be aligned without a big-bang rewrite.
- **Decision**: Treat `MarketView`, `Execution`, and `CostView` as three business modules mounted from one canonical frontend shell in `Execution/frontend/src/App.tsx`. Treat the "one data module" target as a logical data domain with explicit subdomains and contracts, not as an immediate migration to one physical package or one database. The active CostView UI remains `Execution/frontend/src/modules/costview/`; `CostView/frontend/` is downgraded to legacy prototype status pending archival or deletion.
- **Consequences**: The user-facing entry point stays unified while business-domain boundaries become clearer. Future MarketView work has a defined shell anchor. Data-layer alignment can proceed incrementally through contracts and adapters instead of forcing premature storage consolidation. Documentation must now consistently reflect that the frontend shell is canonical and that duplicate UI surfaces are non-authoritative.
- **Review Date**: 2026-05-22

---

## Decision: Logical Data Domain Uses Adapter Entry, Not Forced Storage Unification

- **Date**: 2026-04-22
- **Context**: Execution operational persistence and CostView analytical storage serve different workloads and lifecycles. The architecture needed one coherent data story without collapsing PostgreSQL, in-memory caches, and SQLite analytical stores into a single premature storage model. Cross-domain integration had also started to rely on direct deep imports.
- **Decision**: Introduce a shared adapter entry under `platform_data/` as the canonical access layer for logical platform data. Keep Execution operational data owned by `RepositoryProvider` and CostView analytical data owned by `TcaQueryService`, but surface them through `ExecutionOperationalDataAdapter` and `CostViewAnalyticsAdapter`. Migrate callers incrementally instead of rewriting storage.
- **Consequences**: The platform now has a concrete code-level entry point for shared data access while preserving domain ownership. Cross-domain code can standardize on adapters over time. Some legacy direct imports will remain temporarily and should be reduced incrementally rather than removed all at once.
- **Review Date**: 2026-05-22

---

## Decision: MarketView Starts with Daily Market Snapshot, Not Realtime Stream

- **Date**: 2026-04-22
- **Context**: MarketView needed its first real data boundary, but the repository did not yet have a dedicated pre-trade data service. The existing CostView pipeline already produced stable day-level market metrics in `bdib_daily_summary`, including close, volatility, and ADV fields that are directly relevant to pre-trade analysis.
- **Decision**: Use the latest `bdib_daily_summary` snapshot as MarketView phase-1 data. Surface it through `platform_data` via `MarketReferenceDataAdapter`, expose it with `Execution/backend/api/routers/marketview.py`, and render it in the frontend shell before attempting realtime market streams or order-aware pre-trade recommendation logic.
- **Consequences**: MarketView becomes operational with real data quickly and without adding a second market-data ingestion path. The initial scope stays read-only and day-level, which reduces risk. Realtime streaming and richer pre-trade workflows remain future increments once the shell boundary and adapter path are proven.
- **Review Date**: 2026-05-22

---

## Decision: CostView Regime Layer Schema Conventions (M1)

- **Date**: 2026-04-27
- **Context**: Adding a new analytical layer (regime classification) to CostView; need conventions reusable across future modules (attribution, research outputs).
- **Decision**:
  - 4-layer table prefix: `ref_` / `daily_` / `fill_` (or `event_`) / `audit_`; upper layers only read lower layers.
  - Every non-`ref_` table carries `ingested_at TIMESTAMP NOT NULL` + `source_version TEXT NOT NULL`.
  - Every analytical DB ships `audit_pipeline_runs` + `<module>_status` SQL view + `validate_<module>.py`.
  - Parameterized analytical outputs (e.g. `fill_regime_labels`) include `config_version` in PK; append-only; current params resolved via `audit_<module>_config_versions.is_active=1`.
  - DDL centralized in module-level `schema.py` with `SCHEMA_VERSION` constant; any DDL change requires bump + `migrations/vN_to_vN+1.sql`.
  - Pragma triple on every DB: `journal_mode=WAL; foreign_keys=ON; user_version=N`.
  - Date type: `TEXT 'YYYY-MM-DD'` for all new tables. Legacy `'YYYYMMDD'` (raw_bdib, bdib_daily_summary) is technical debt; not migrated now.
- **Consequences**: Reproducibility (param drift preserved), recovery (audit_pipeline_runs), observability (status view), low-friction onboarding for new analytical DBs. Cost: more boilerplate per table.
- **Codified at**: [.github/skills/schema-designer/SKILL.md](../skills/schema-designer/SKILL.md) + [.github/agents/schema-designer.agent.md](../agents/schema-designer.agent.md) + `/memories/repo/schema-design-conventions.md`.
- **Review Date**: 2026-07-01 (after M1+M2 ship to verify principles hold)
- **Status**: Active



---

## Decision: Defer IV / Spread / Depth Inputs to Vol/Liq Regime (P2)

- **Date**: 2026-04-28
- **Context**: Original 项目功能构建规划.md M1 plan calls for IV (implied volatility) inside vol_regime and bid-ask spread + book depth inside liq_regime. Bloomberg BDIB feed (raw_bdib) carries OHLCV + vwap only; no NBBO, no IV chain, no order book depth. Adding these would require enabling Bloomberg BVOL / BPIPE depth feeds and a new ingestion pipeline.
- **Decision**: Keep current schema (v3) using ATR-based vol_regime and ADV-based liq_regime as in M1. Postpone IV / spread / depth integration to Phase 2 (M4+). When integrated, add nullable columns `iv_pct`, `spread_pct`, `depth_proxy` to `daily_vol_regime` / `daily_liquidity_regime` via schema v4 migration; current rows keep NULL.
- **Consequences**: Vol regime is realized-vol-only (ATR proxy), missing forward-looking signal. Liq regime ignores microstructure. Recommendations may be biased toward historically calm names. Mitigation: add a manually-curated `is_macro_day_pm1` flag to capture event-driven regime shifts.
- **Review Date**: 2026-07-01 (Phase 2 kickoff or earlier when BVOL / depth feeds become available)

---

## Decision: Off-book Trades Cap participation_rate at 5x

- **Date**: 2026-04-28
- **Context**: P0.1 added `participation_rate = route_shares / Σ(BDIB bar volume over [first_min, last_min])`. Schema v3 already constrains `participation_rate IN [0, 5]` to reject obvious junk. Real-world routes that fill against dark/off-book liquidity (e.g. blocks, internalised crosses) often produce ratios > 1 because the on-book bar volume excludes those prints.
- **Decision**: When the computed ratio exceeds 5x, store NULL instead. Aggregator treats NULL as "unknown" (excluded from cell). Rows < 0 (impossible by definition) also become NULL.
- **Consequences**: Avoids CHECK constraint failures during backfill while preserving the analytic integrity of the column for on-book scenarios. Loses signal for highly off-book strategies; deferred mitigation: separate `dark_pool_share` column when broker-tagging is integrated.
- **Review Date**: 2026-06-01

---

## Decision: ProcessedFillsDB God Object Decomposition — Repository Package

- **Date**: 2026-05-07
- **Context**: `processed_fills_db.py` was a 1149-line, 39-method God Object managing 15 tables (6 business domains). Modularity score was 2/5 (Poor). The `attribution/` module had already established a Protocol-driven DI pattern (dto → protocols → repositories).
- **Decision**: Decompose into a `processed_fills_db/` package with 8 domain-specific repositories + 1 backward-compatible Facade:
  - `_base.py`: Shared `BaseProcessedFillsRepo` (connection management, access control) + `init_processed_fills_schema()` (coordinated DDL for all 15 tables)
  - `fills_repository.py`: ProcessedFillsRepository (5 methods — processed_fills + route_registry)
  - `aggregation_repository.py`: AggregationRepository (4 methods — agg_fills_10s/1min)
  - `execution_history_repository.py`: ExecutionHistoryRepository (4 methods — order/route/event history)
  - `order_label_repository.py`: OrderLabelRepository (3 methods — order_label)
  - `processing_log_repository.py`: ProcessingLogRepository (3 methods — processing_log)
  - `ticker_repository.py`: TickerRepository (7 methods — 4 ticker metadata tables)
  - `legacy_repository.py`: LegacyRepository (5 methods — deprecated dynamic-schema tables)
  - `stats.py`: Cross-domain `get_processing_stats()` (reads all tables)
  - `facade.py`: `ProcessedFillsDB` class delegating 33 methods to sub-repositories
  - `__init__.py`: Re-exports Facade + all Repository classes
  - Original `processed_fills_db.py` → `processed_fills_db._legacy_backup.py`
- **Consequences**: Each repo is ≤200 lines (well under 500-line limit); callers import `ProcessedFillsDB` unchanged; new code can import specific repositories; Schema init is coordinated in one place; `_upsert_fixed_schema()` is a static method on `BaseProcessedFillsRepo` available to all repos.
- **Review Date**: 2026-08-01 (or when Phase 3 Protocol extraction is attempted)

---

## Decision: CostView Database Subsystem Phase 1 — Unified Connection Management + Protocol Definitions

- **Date**: 2026-05-07
- **Context**: CostView data layer had 3 coexisting access patterns (raw SQL, DB classes, Repository Protocol) with no centralized connection management. 6 SQLite databases were accessed via scattered `sqlite3.connect()` calls. The `costview.py` router used raw SQL to query `regime.db`. Pipeline context held 5 independent DB instances with no unified lifecycle.
- **Decision**: Introduce `CostView/src/db/` package with: (1) `ConnectionManager` — centralized connection lifecycle for all 6 databases with standard pragmas (WAL, foreign_keys, busy_timeout) and access tier enforcement; (2) `protocols.py` — 12 Repository Protocols (read/write/admin for fills, market data, integrated, regime) + `FillQueryBuilder` escape hatch; (3) `dto.py` — pure data transfer objects for cross-database operations; (4) `database_access.py` → backward-compat re-export module. Migrated all `from .database_access import` to `from .db.connection import` across 10 files. Eliminated raw `sqlite3.connect()` in `costview.py` router (regime-distribution endpoint). Added `ConnectionManager` to `PipelineContext` with lazy initialization.
- **Consequences**: All CostView internal DB classes now import from `db.connection` instead of `database_access.py`. External callers still work via `database_access.py` re-export. `costview.py` router no longer uses raw sqlite3. `ConnectionManager` provides path registry for all 6 databases + existence checks + admin connection factory. Foundation laid for Phase 2 (Repository implementations) and Phase 3 (cross-module decoupling via platform_data contracts).
- **Review Date**: 2026-08-01 (or when Phase 2 Repository implementation begins)

---

## Decision: CostView Database Subsystem Phase 2 — Repository Implementations + Unified Schema Management

- **Date**: 2026-05-07
- **Context**: Phase 1 established ConnectionManager and Protocol definitions. Phase 2 needed concrete Repository implementations using ConnectionManager, a unified MigrationManager, and a facade for backward compatibility. The `attribution/repositories.py` contained 3 repositories (SqliteFillRepository, SqliteBarDataRepository, SqliteRegimeRepository) with their own connection management, and `processed_fills_db/` had 8 sub-repositories using BaseProcessedFillsRepo.
- **Decision**: Created `db/repositories/` package with 10 concrete repository classes implementing Phase 1 Protocol interfaces: fills_read, fills_write, raw_fills_read, raw_fills_write, market_data_read, market_data_write, integrated (read+write), regime (read+write). All use `ConnectionManager` for connections. Created `db/schema/` package with `columns.py` (migrated from schema.py) and `migrations/manager.py` (MigrationManager tracking PRAGMA user_version for all 6 DBs). Created `db/facade.py` (CostViewDatabase) providing unified access to all repositories + health check. Created `db/dto.py` with attribution DTOs (migrated from attribution/dto.py). Regime repository merged functionality from attribution/repositories.py + storage/regime_reader.py.
- **Consequences**: All 6 databases now have read+write repository implementations using ConnectionManager. MigrationManager provides unified schema version tracking (regime.db at v3, others at v0 with inline DDL). CostViewDatabase facade provides single entry point. Existing attribution repositories remain functional (unchanged imports). 56/56 tests pass. The `db/schema/columns.py` is now the canonical source for column definitions alongside the original `schema.py`.
- **Review Date**: 2026-08-01 (or when Phase 3 cross-module decoupling begins)

---

## Decision: CostView Database Subsystem Phase 3 — Cross-Module Decoupling via Contracts + CostViewDatabaseAdapter

- **Date**: 2026-05-07
- **Context**: Phase 1+2 established ConnectionManager, Repository implementations, and CostViewDatabase facade within CostView. However, cross-module data access still had three violations: (1) ExecutionView's `costview.py` router directly imported `SCORECARD_COHORTS` from `CostView.src.tca_query_service`; (2) the same router used `ConnectionManager` directly to query `regime.db` with raw SQL; (3) `platform_data/repositories.py` depended on `CostView.src.processing_config.ProcessingConfig` for database paths and table names. These violated the architecture principle that `platform_data` is the sole legal entry point for cross-module data access.
- **Decision**: (1) Created `platform_data/contracts/` package with `fill_contracts.py` (SCORECARD_COHORTS + FillContract), `market_data_contracts.py` (ADVRecordContract, DailySummaryContract, IntradayBarContract), and `regime_contracts.py` (RegimeDistributionContract, RegimeDistributionResultContract) — pure dataclass constants with zero CostView imports, serving as the stable cross-module interface. (2) Migrated SCORECARD_COHORTS from `CostView.src.tca_query_service` to `platform_data.contracts.fill_contracts`; updated ExecutionView import to `from platform_data.contracts import SCORECARD_COHORTS`. (3) Added `CostViewDatabaseAdapter` to `platform_data/adapters.py` with `get_regime_distribution()` method that encapsulates regime.db SQL behind the adapter interface; updated `PlatformDataAccess` to include `database: CostViewDatabaseAdapter` field. (4) Replaced direct `ConnectionManager` usage in `costview.py` router's regime-distribution endpoint with `CostViewDatabaseAdapter.get_regime_distribution()`. (5) Eliminated `platform_data/repositories.py` dependency on `ProcessingConfig` by using `ConnectionManager.get_all_paths()` for database paths and hardcoding stable table name constants (`_RAW_FILLS_TABLE`, `_FETCH_LOG_TABLE`, etc.) within the module.
- **Consequences**: Zero `from CostView.src.*` imports remain in ExecutionView. `platform_data/repositories.py` no longer depends on `CostView.src.processing_config`. Cross-module data access flows exclusively through `platform_data` adapters and contracts. The `CostViewDatabaseAdapter` provides a clean read-only interface for regime/fills/market data queries. Internal CostView code (`tca_query_service.py`) still has its own `SCORECARD_COHORTS` for backward compatibility; the contracts layer is the canonical cross-module source.
- **Review Date**: 2026-08-01


---

## Decision: Migration Stub Cleanup — Delete Re-Export Stubs (Iteration 4)

- **Date**: 2026-05-08
- **Context**: Iterations 1-3 migrated logic to DataPipeline, leaving backward-compatible re-export stubs at old import paths. All internal callers had been updated.
- **Decision**: Delete 5 re-export stub files (pipeline.py, processing_config.py, schema.py, daily_metrics_calculator.py, bdib_fetcher.py). Migrate remaining 8 files still importing old processing_config path. Add CI lint script enforcing sqlite3.connect() only in allowed directories.
- **Consequences**: Cleaner import graph; no more deprecation warnings from internal modules. CI enforces the rule.
- **Review Date**: 2026-08-01

---

## Decision: FillFetchDatabase SQLAlchemy → ConnectionManager Migration (Iteration 5.1)

- **Date**: 2026-05-08
- **Context**: FillFetchDatabase used standalone SQLAlchemy engine outside ConnectionManager. Database path via env var, not ProcessingConfig.
- **Decision**: Rewrite FillFetchDatabase to use ConnectionManager + native sqlite3. Register DB_FETCH_HISTORY as 7th managed database. Keep 100% backward-compatible API.
- **Consequences**: Zero SQLAlchemy dependency. fill_fetch_history.db is first-class managed database.
- **Review Date**: 2026-08-01

---

## Decision: downstream_interface → FillReadRepository Protocol (Iteration 5.2)

- **Date**: 2026-05-08
- **Context**: downstream_interface had 4 functions defaulting to ProcessedFillsDB() concrete class.
- **Decision**: Add ticker registry methods to FillReadRepository Protocol. Change function signatures to accept FillReadRepository. Default: SqliteFillReadRepository().
- **Consequences**: Zero direct ProcessedFillsDB references. Accepts any FillReadRepository implementation.
- **Review Date**: 2026-08-01

---

## Decision: ProcessingConfig Instance Injection Support (Iteration 6.1)

- **Date**: 2026-05-08
- **Context**: ProcessingConfig was purely static class — no instance override possible.
- **Decision**: Add __init__(**overrides) + __getattribute__. Instance attribs take precedence. Static access fully backward-compatible.
- **Consequences**: Testing with isolated config instances now possible. Gradual DI migration enabled.
- **Review Date**: 2026-08-01

---

## Decision: Centralized Table Name Registry (Iteration 6.2)

- **Date**: 2026-05-08
- **Context**: Table names duplicated across processing_config.py, platform_data/repositories.py (5 repeated), and connection.py.
- **Decision**: Create DataPipeline/src/common/table_registry.py as single source of truth for 22 table + 7 DB key constants.
- **Consequences**: Single change point for table renames. Zero duplicate string literals.
- **Review Date**: 2026-08-01

---

## Decision: tca_query_service Module Split (Iteration 6.3)

- **Date**: 2026-05-08
- **Context**: tca_query_service.py had 1,435 lines combining 7 dataclasses, SQL builders, fallback logic, and orchestrator.
- **Decision**: Extract 7 dataclasses + 2 constants into tca_types.py. Keep backward compat via rom .tca_types import *.
- **Consequences**: File drops to ~1,230 lines. Types isolable for future contract migration. 42/42 TCA tests pass.
- **Review Date**: 2026-08-01

---

## Decision: Eliminate platform_data Reverse Imports via TCA Contracts (Iteration 7.1)

- **Date**: 2026-05-08
- **Context**: platform_data/adapters.py imported TCA dataclasses from CostView, creating circular import when tca_types referenced contracts.
- **Decision**: Create platform_data/contracts/tca_contracts.py as canonical TCA type home. tca_types imports from contracts. adapters imports types from contracts and uses lazy TcaQueryService factory. Fix 3 remaining broken CostView.src references.
- **Consequences**: Zero CostView src imports in platform_data for types. Circular chain broken. Single contract type source.
- **Review Date**: 2026-08-01

---

## Decision: ConnectionManager Thread-Local Connection Cache (Iteration 6.3 optimization)

- **Date**: 2026-05-08
- **Context**: High-frequency short-query workloads (regime tagger, pipeline guards)
  created a new ``sqlite3.Connection`` per call (~50µs overhead).  The original
  Phase 1 design chose "fresh connection per call" deliberately because SQLite
  connections cannot be shared across threads.
- **Decision**: Add ``threading.local()`` connection cache to ``ConnectionManager``.
  Only READ-tier connections are cached, keyed by ``(database_name, row_factory)``.
  WRITE and ADMIN connections always create a fresh connection.  The cache is
  per-thread so no cross-thread sharing.  A ``close_thread_cached_connections()``
  method allows explicit invalidation.  Stale connections (e.g. after DB rebuild)
  are detected via a ``SELECT 1`` ping and automatically evicted.
- **Consequences**: Read workloads reuse connections within a thread, avoiding
  ~50µs/connection overhead.  Thread safety preserved.  Zero API change.
- **Review Date**: 2026-11-01
