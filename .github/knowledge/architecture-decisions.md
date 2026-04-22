# Architecture Decisions Log

> Auto-maintained by the iterative update mechanism. Records architectural decisions, their context, and review schedule.

---

## Decision: Single-File Backend (main.py)

- **Date**: 2026-03 (initial design)
- **Context**: Fast iteration during early development; Bloomberg blpapi requires specific session lifecycle management; all EMSX operations are tightly coupled
- **Decision**: Keep all backend logic in a single `main.py` file (~3695 lines) with FastAPI + blpapi
- **Consequences**: Easy to search and understand data flow; difficult to test in isolation; merge conflicts likely with multiple contributors; IDE performance degrades
- **Technical Debt**: HIGH — file exceeds 3000-line threshold; contains models, routes, Bloomberg session management, and business logic in one file
- **Review Date**: 2026-04-16 (next major feature)

---

## Decision: No Redux — React Hooks + Context

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
- **Decision**: Two SQLite databases — `raw_fills.db` (TEXT columns for schema flexibility) and `processed_fills.db` (typed columns + aggregations + labels)
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
- **Decision**: Add ThreadPoolExecutor-based parallelism with per-thread DB connections (max 4 dates, max 3 tickers). Falls back to serial when max_workers≤1. Configurable via `MAX_PARALLEL_DATES` and `MAX_PARALLEL_TICKERS` in `processing_config.py`.
- **Consequences**: Expected 2-4x speedup on multi-date runs; each thread creates its own RawFillsDB/ProcessedFillsDB instance avoiding connection sharing; requires Phase 1.2 transaction atomicity (optional `conn` param on write methods) to be in place first.
- **Review Date**: 2026-06-01

---

## Decision: Vectorized Timezone Conversion via batch_convert_ny_to_local

- **Date**: 2026-04-15
- **Context**: `derive_exchange_times()` used per-row `iterrows()` + `convert_ny_to_local()` — O(N) ZoneInfo lookups. For 100k fills, this was the single largest bottleneck.
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
