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
- **Decision**: Use `docs/EXECUTION_PLATFORM_WBS.md` as the human-readable source plan and `.workbuddy/plans/execution-platform-status.yaml` + `.workbuddy/plans/execution-platform-risk-register.yaml` as the authoritative machine-readable delivery ledger for sprint state, issue dependencies, checkpoints, and risks.
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


