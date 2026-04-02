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
