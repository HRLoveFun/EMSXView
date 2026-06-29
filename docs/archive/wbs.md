# EMSX ExecutionView Platform Work Breakdown Structure

**Document Path**: `c:/Users/hrchen/Documents/EMSX/docs/roadmap/wbs.md`
**Requested**: 2026-04-02
**Scope**: `frontend/src/modules/execution/`, `CostView/`, repo-level workflow automation under `.github/`, `.workbuddy/`, and `scripts/`
**Planning Horizon**: 9 sprints across 6 phases
**Delivery Model**: Incremental refactor; every sprint must leave the system deployable

---

## 1. Objectives

This document converts the target-state architecture plan into a comprehensive work breakdown structure with:

- phase-by-phase delivery sequencing
- sprint-level, issue-sized tasks
- explicit file creation/update plans
- technical implementation details per file
- dependency and checkpoint definitions
- a persistent workflow system for execution, monitoring, and continuity

This plan assumes the current codebase remains the delivery baseline, with the existing runtime centered on:

- `c:/Users/hrchen/Documents/EMSX/backend/api/main.py`
- `c:/Users/hrchen/Documents/EMSX/backend/api/auth.py`
- `c:/Users/hrchen/Documents/EMSX/frontend/src/App.tsx`
- `c:/Users/hrchen/Documents/EMSX/frontend/src/services/api.ts`
- `c:/Users/hrchen/Documents/EMSX/CostView/src/emsx_client.py`

---

## 2. Delivery principles

### 2.1 Non-negotiable constraints

1. No big-bang rewrite.
2. Every sprint must preserve a working system state.
3. New backend modules must be introduced behind the existing API surface first.
4. Realtime delivery must be added before polling is removed as the primary mechanism.
5. Durable persistence must exist before advanced execution logic is introduced.
6. TCA feedback must exist before recommendation/ranking logic is trusted.

### 2.2 Standard sprint checkpoints

Each sprint must pass the following gates before merge:

- Backend starts locally and in Docker
- Frontend builds successfully
- No new TypeScript or Pydantic schema drift
- New/updated tests pass
- Integration smoke test passes for changed API flows
- Architecture decision log is updated for structural changes
- Workflow status artifacts are updated

### 2.3 Sprint cadence

- **Sprint length**: 2 weeks
- **Merge model**: short-lived feature branches, PR-based integration
- **Release model**: one tagged release candidate per sprint

---

## 3. Phase and sprint summary

| Phase | Sprints | Outcome |
|---|---:|---|
| Phase 0 - Workflow Foundation | 0 | Persistent planning, tracking, QA, and progress automation |
| Phase 1 - Durable ExecutionView Core | 1-2 | Postgres-backed state and realtime delivery foundation |
| Phase 2 - Modular Service Extraction | 3-4 | `main.py` decomposed into service/router/config/auth layers |
| Phase 3 - Advanced ExecutionView Engine | 5-6 | Parent-child order orchestration and benchmark execution support |
| Phase 4 - CostView Closed Loop | 7-8 | Fill linkage, TCA metrics, and broker/strategy feedback loop |
| Phase 5 - Intelligence Layer | 9 | CEP surveillance, replay, and recommendation framework |

---

## 4. Persistent workflow system design

## 4.1 Workflow architecture

```text
Plan Source -> Sprint Board -> Issue/PR Execution -> CI/QA Gates -> Progress Ledger -> Review Gate -> Release/Handoff
     |               |                  |                |                |               |
     |               |                  |                |                |               +-> docs/handoff.md
     |               |                  |                |                +-> .workbuddy/knowledge/metrics.md
     |               |                  |                +-> .github/workflows/*.yml
     |               |                  +-> Git branches / PR templates / commit conventions
     |               +-> machine-readable sprint state under plans/
     +-> this WBS document under docs/
```

## 4.2 Workflow components

### A. Automated task tracking

Use a dual layer:

1. **Human-readable master plan**
   - `c:/Users/hrchen/Documents/EMSX/docs/roadmap/wbs.md`
2. **Machine-readable sprint ledger**
   - `c:/Users/hrchen/Documents/EMSX/plans/execution-platform-status.yaml`
   - stores current phase, sprint, issue state, blockers, checkpoint state, and release tag

### B. Version control integration

Use branch naming and PR templates:

- Branch format: `phase-{n}/sprint-{n}/{issue-key}-{slug}`
- Commit prefix format: `P{phase}-S{sprint}-{issue}: message`
- PR must link sprint issue keys and update checkpoint results

### C. Progress monitoring

Persist sprint status to:

- `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/iteration-log.md`
- `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/metrics.md`
- `c:/Users/hrchen/Documents/EMSX/docs/handoff.md`

### D. Quality assurance checkpoints

Automate these in CI and local scripts:

- backend unit tests
- frontend unit tests
- API smoke tests
- lint and typecheck
- migration validation
- coverage threshold enforcement
- architecture review checklist for structural PRs

### E. Continuity mechanisms

Link all workflow artifacts using a shared sprint key, e.g. `P1-S2`.

Every artifact must carry:

- phase ID
- sprint ID
- issue ID
- owner
- dependency IDs
- checkpoint status
- merge status

## 4.3 Workflow-system implementation backlog

### Sprint 0 exit criteria

- Persistent sprint ledger exists
- CI gates exist for backend and frontend
- PR template requires sprint/issue/checkpoint completion
- Daily automation updates metrics and handoff status
- Structural changes must update architecture knowledge

### Sprint 0 issue list

#### Issue P0-S0-01 - Create machine-readable sprint ledger
- **Depends on**: none
- **Acceptance**:
  - YAML ledger defines phases, sprints, issues, statuses, blockers, and checkpoints
  - ledger can be updated by script without manual reformatting

#### Issue P0-S0-02 - Wire task and PR workflow templates
- **Depends on**: P0-S0-01
- **Acceptance**:
  - issue and PR templates capture sprint key, dependencies, and acceptance criteria
  - branch/PR workflow is documented and enforceable

#### Issue P0-S0-03 - Add CI/QA orchestration
- **Depends on**: P0-S0-02
- **Acceptance**:
  - backend and frontend checks run independently and as a combined gate
  - failures block merge

#### Issue P0-S0-04 - Add automated progress and handoff updates
- **Depends on**: P0-S0-01, P0-S0-03
- **Acceptance**:
  - script updates metrics and iteration log from ledger + CI state
  - handoff summary includes current sprint progress and open blockers

### Sprint 0 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/plans/execution-platform-status.yaml` | create | Persistent machine-readable plan ledger | YAML structure for phase/sprint/issue/checkpoint state; used by scripts and automations | None |
| `c:/Users/hrchen/Documents/EMSX/plans/execution-platform-risk-register.yaml` | create | Track blockers, architecture risks, and mitigation owners | YAML keyed by risk ID with severity, trigger, mitigation, sprint linkage | None |
| `c:/Users/hrchen/Documents/EMSX/.github/ISSUE_TEMPLATE/execution-platform-task.yml` | create | Standardize issue-sized tasks | Fields: sprint key, phase, dependency IDs, acceptance criteria, checkpoint list | P0-S0-01 |
| `c:/Users/hrchen/Documents/EMSX/.github/PULL_REQUEST_TEMPLATE/execution-platform.md` | create | Enforce PR metadata and checkpoint completion | Checklist for tests, docs, migration impact, rollback, sprint ledger update | P0-S0-02 |
| `c:/Users/hrchen/Documents/EMSX/.github/workflows/execution-platform-ci.yml` | create | CI entrypoint for backend/frontend/test gates | Matrix jobs for Python and Node; branch protections consume this workflow | P0-S0-03 |
| `c:/Users/hrchen/Documents/EMSX/.github/workflows/execution-platform-progress.yml` | create | Update plan status from CI/merge events | Triggers on PR merge and manual dispatch; calls progress sync script | P0-S0-03 |
| `c:/Users/hrchen/Documents/EMSX/scripts/workflow/sync_execution_status.py` | create | Synchronize ledger, iteration log, and metrics | Parses YAML ledger; updates Markdown summaries; emits JSON status | P0-S0-01 |
| `c:/Users/hrchen/Documents/EMSX/scripts/workflow/validate_phase_gate.py` | create | Validate sprint entry/exit criteria | Checks dependency completion and required artifacts before phase promotion | P0-S0-01 |
| `c:/Users/hrchen/Documents/EMSX/scripts/workflow/generate_handoff_snapshot.py` | create | Build sprint-aware handoff summaries | Reads ledger + iteration log + risk register; outputs current status snapshot | P0-S0-04 |
| `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/iteration-log.md` | update | Record sprint and issue execution | Add structured entries per sprint transition and failed checkpoints | P0-S0-04 |
| `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/metrics.md` | update | Persist progress KPIs | Add sprint throughput, checkpoint pass rate, defect escape rate, lead time | P0-S0-04 |
| `c:/Users/hrchen/Documents/EMSX/.github/instructions/task-planning.instructions.md` | update | Align planner rules to sprint-ledger workflow | Require sprint key references and ledger update before plan completion | P0-S0-02 |
| `c:/Users/hrchen/Documents/EMSX/.workbuddy/automations/session-capture-daily/automation.toml` | update | Include sprint-state capture in daily automation | Prompt must read workflow ledger and current blockers | P0-S0-04 |
| `c:/Users/hrchen/Documents/EMSX/.workbuddy/automations/handoff-merge-daily/automation.toml` | update | Merge sprint progress into handoff | Add dependency on generated handoff snapshot artifact | P0-S0-04 |

---

# 5. Phase 1 - Durable ExecutionView Core

## 5.1 Sprint 1 - Persistent storage foundation

### Sprint objective
Introduce durable backend persistence without breaking the current API surface.

### Sprint dependencies
- Phase 0 complete

### Sprint 1 issue list

#### Issue P1-S1-01 - Add backend persistence dependencies and container services
- **Depends on**: Phase 0
- **Acceptance**:
  - Postgres service starts through Docker Compose
  - backend image includes database and migration dependencies

#### Issue P1-S1-02 - Create database session and schema bootstrap
- **Depends on**: P1-S1-01
- **Acceptance**:
  - backend can create DB sessions and initialize schema
  - health endpoint reports DB connectivity

#### Issue P1-S1-03 - Persist order/route/audit projections
- **Depends on**: P1-S1-02
- **Acceptance**:
  - subscription updates can be written to durable tables
  - audit events persist for modify/cancel/route actions

#### Issue P1-S1-04 - Add repository abstraction under current API handlers
- **Depends on**: P1-S1-03
- **Acceptance**:
  - HTTP handlers read from repositories instead of raw in-memory-only paths where feasible
  - fallback to in-memory remains available during rollout

### Sprint 1 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/docker-compose.yml` | update | Add Postgres service and volumes | Add `postgres` container, env vars, startup dependency wiring, and health checks | P1-S1-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/requirements.txt` | update | Add persistence stack | Add `sqlalchemy`, `asyncpg`, `alembic`, `psycopg[binary]`, `pytest-cov` | P1-S1-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/Dockerfile` | update | Copy modular backend files and install DB tooling | Change from copying only `main.py`/`auth.py` to copying package directories and migration assets | P1-S1-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/db.py` | create | DB engine and session factory | Async SQLAlchemy engine, sessionmaker, lifecycle helpers, retryable startup probe | P1-S1-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/models/execution_state.py` | create | ORM models for order, route, audit, and watermark state | Tables for `orders_projection`, `routes_projection`, `audit_events`, `subscription_watermarks` | P1-S1-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/repositories/orders.py` | create | Order projection persistence and queries | Upsert by EMSX sequence, projection fetch, filter composition, pagination hooks | P1-S1-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/repositories/routes.py` | create | Route projection persistence and queries | Upsert by composite key, parent linkage, enrichment field persistence | P1-S1-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/repositories/audit.py` | create | Command audit persistence | Store request actor, endpoint, payload summary, result, correlation ID | P1-S1-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/migrations/001_init_execution_schema.sql` | create | Initial SQL schema | DDL for projection, audit, watermark, and config tables with indexes | P1-S1-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/main.py` | update | Bootstrap DB and route reads/writes through repositories | Inject DB lifecycle, dual-write projection updates, health/reporting changes | P1-S1-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/auth.py` | update | Include correlation IDs in audit context | Extend auth context for audit trail linkage | P1-S1-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_db_bootstrap.py` | create | Validate DB initialization | Test engine creation, schema bootstrap, and simple repository roundtrip | P1-S1-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_projection_repositories.py` | create | Validate order/route projection persistence | Repository-level tests for upsert/query behavior and watermarks | P1-S1-03 |

---

## 5.2 Sprint 2 - Realtime projections and stream-based UI path

### Sprint objective
Introduce a supported realtime path and reduce dependence on full polling snapshots.

### Sprint dependencies
- Sprint 1 complete

### Sprint 2 issue list

#### Issue P1-S2-01 - Build backend realtime gateway
- **Depends on**: Sprint 1
- **Acceptance**:
  - backend emits order/route delta events on projection updates
  - WebSocket endpoint supports reconnect and cursor/backfill

#### Issue P1-S2-02 - Add frontend realtime client abstraction
- **Depends on**: P1-S2-01
- **Acceptance**:
  - frontend can subscribe to order/route deltas
  - reconnect and snapshot fallback are automatic

#### Issue P1-S2-03 - Move App state from polling-first to stream-first
- **Depends on**: P1-S2-02
- **Acceptance**:
  - initial snapshot + delta updates drive the blotter
  - polling remains fallback only

#### Issue P1-S2-04 - Add stream integration tests and observability
- **Depends on**: P1-S2-01, P1-S2-03
- **Acceptance**:
  - event-to-screen latency measurable
  - integration tests cover reconnect/backfill

### Sprint 2 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/realtime_gateway.py` | create | Publish order/route delta events to clients | Connection registry, cursor-based subscriptions, replay from projection watermark | P1-S2-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/event_serializers.py` | create | Normalize delta payloads | Stable event schema with event type, entity key, version, timestamp, patch | P1-S2-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/main.py` | update | Wire projection updates into realtime gateway | Publish after commit; keep `/ws/orders` compatible during transition | P1-S2-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/config/nginx.conf` | update | Support hardened WS/SSE proxying | Tune timeouts, upgrade headers, optional `/ws/routes` or `/stream/*` support | P1-S2-01 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/realtime.ts` | create | Realtime client transport | WebSocket client with reconnect, heartbeat, cursor resume, backfill hook | P1-S2-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/hooks/use-orders-stream.ts` | create | Stream-backed order state hook | Initial REST snapshot then delta merge into local store | P1-S2-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/hooks/use-routes-stream.ts` | create | Stream-backed route state hook | Shared merge logic and reconnect semantics | P1-S2-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/stores/order-stream-store.ts` | create | Normalize order delta application | Entity map + version checks + partial patch merge | P1-S2-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/stores/route-stream-store.ts` | create | Normalize route delta application | Parent-child synchronization and dedupe logic | P1-S2-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/App.tsx` | update | Replace high-frequency polling with stream hooks | Keep periodic fallback only when stream disconnected | P1-S2-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/api.ts` | update | Support initial snapshot + cursor backfill APIs | Add helper for bootstrap snapshots and projection version metadata | P1-S2-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/package.json` | update | Add frontend test tooling | Add `vitest`, `@testing-library/react`, `msw` | P1-S2-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/realtime.test.ts` | create | Validate reconnect/backfill behavior | Mock WS transport and verify cursor resume | P1-S2-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_realtime_gateway.py` | create | Validate gateway fanout and cursor replay | Integration tests for delta serialization and replay ordering | P1-S2-04 |

---

# 6. Phase 2 - Modular Service Extraction

## 6.1 Sprint 3 - Extract Bloomberg adapter and projection services

### Sprint objective
Decompose `main.py` into stable service modules while keeping the current API surface intact.

### Sprint dependencies
- Phase 1 complete

### Sprint 3 issue list

#### Issue P2-S3-01 - Extract EMSX connection and subscription adapter
- **Depends on**: Phase 1
- **Acceptance**:
  - Bloomberg session lifecycle no longer lives directly in route handlers
  - adapter is testable in isolation with mocked `blpapi`

#### Issue P2-S3-02 - Extract projection and enrichment services
- **Depends on**: P2-S3-01
- **Acceptance**:
  - projection updates and enrichment responsibilities are modular
  - repository writes are not embedded in transport code

#### Issue P2-S3-03 - Extract command services
- **Depends on**: P2-S3-01
- **Acceptance**:
  - order/route modify/cancel/route logic moved into service modules

#### Issue P2-S3-04 - Add architecture regression tests
- **Depends on**: P2-S3-01, P2-S3-02, P2-S3-03
- **Acceptance**:
  - module tests cover service boundaries and mock-based Bloomberg flows

### Sprint 3 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/emsx_adapter.py` | create | Encapsulate session lifecycle and subscription loops | Move session connect/disconnect, request session, mktdata session, subscription threading | P2-S3-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/emsx_requests.py` | create | Encapsulate request/response commands to EMSX | Move request builders for ModifyOrderEx, ModifyRouteEx, RouteEx, Cancel* | P2-S3-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/emsx_subscriptions.py` | create | Encapsulate INIT_PAINT/live event processing | Normalize message parsing and event-status transitions | P2-S3-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/projection_service.py` | create | Own projection writes and read models | Receive normalized events and persist order/route projection updates | P2-S3-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/market_enrichment.py` | create | Own FX/ADV/VWAP/refdata enrichment | Move market enrichment caches and refresh logic into dedicated service | P2-S3-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/execution_commands.py` | create | Own command orchestration | Validate requests, call EMSX request service, persist audit, publish events | P2-S3-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/main.py` | update | Reduce to app composition and dependency wiring | Remove transport/business logic bodies; register services and inject routers | P2-S3-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_emsx_adapter.py` | create | Validate adapter lifecycle | Mock session startup, service open, subscription sequencing, reconnect behavior | P2-S3-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_execution_commands.py` | create | Validate command orchestration | Mock EMSX request service and verify audit/projection publication | P2-S3-04 |
| `c:/Users/hrchen/Documents/EMSX/.github/knowledge/architecture-decisions.md` | update | Record extraction decisions | Log service-boundary decisions, consequences, and review dates | P2-S3-04 |

---

## 6.2 Sprint 4 - Router split, auth policy, and config control plane foundation

### Sprint objective
Separate API routing concerns and unify auth/policy/config handling.

### Sprint dependencies
- Sprint 3 complete

### Sprint 4 issue list

#### Issue P2-S4-01 - Split HTTP routers by domain
- **Depends on**: Sprint 3
- **Acceptance**:
  - orders/routes/auth/config/realtime routers exist and are composed in app bootstrap

#### Issue P2-S4-02 - Normalize session/auth/policy context
- **Depends on**: P2-S4-01
- **Acceptance**:
  - local bypass, JWT, and desk/trader policy are explicit and testable

#### Issue P2-S4-03 - Move broker/algo config from JSON-plus-localStorage model toward server-owned config
- **Depends on**: P2-S4-01
- **Acceptance**:
  - backend stores versioned config records
  - frontend settings read through typed APIs first

#### Issue P2-S4-04 - Add configuration and auth regression tests
- **Depends on**: P2-S4-02, P2-S4-03
- **Acceptance**:
  - config versioning and policy checks are covered by tests

### Sprint 4 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/orders.py` | create | Order endpoints by domain | Move `/api/orders*` handlers out of app root | P2-S4-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/routes.py` | create | Route endpoints by domain | Move `/api/routes*` handlers into route router | P2-S4-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/auth.py` | create | Auth endpoints | Isolate login/session introspection endpoints | P2-S4-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/config.py` | create | Broker/algo/config endpoints | Expose versioned configuration APIs | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/realtime.py` | create | Realtime endpoints | Own WS/SSE endpoints and transport negotiation | P2-S4-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/auth_service.py` | create | Central auth behavior | Encapsulate token creation, validation, identity normalization, auth mode policy | P2-S4-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/policy_service.py` | create | Desk/trader authorization rules | Validate trader ownership, allowed desks, and admin vs trader actions | P2-S4-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/config_service.py` | create | Versioned server-side config store | Replace file-first workflow with DB-owned broker/strategy metadata versions | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/repositories/config_repository.py` | create | Persist configuration versions and approvals | Tables and access patterns for config versions, publish state, and audit | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/auth.py` | update | Delegate to auth/policy services | Keep compatibility shim while moving implementation to service layer | P2-S4-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/main.py` | update | Compose routers and domain services | App startup reduced to dependency container and router registration | P2-S4-01 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/session.ts` | create | Frontend session abstraction | Session bootstrap, token handling, auth mode awareness, trader context | P2-S4-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/hooks/use-broker-algorithms.ts` | update | Read server-owned config first | Change cache precedence from localStorage-first to backend-version-first | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/strategy-data-service.ts` | update | Demote file-based fallback to bootstrap-only | Keep static files as disaster fallback, not primary store | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/SettingsBoard.tsx` | update | Surface config version/publish status | Add config version indicators, refresh/publish controls, server sync status | P2-S4-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_auth_policy.py` | create | Validate auth and policy matrix | Unit tests for bypass/JWT/admin/trader scenarios and ownership rules | P2-S4-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_config_service.py` | create | Validate versioned config behavior | Version creation, publish, retrieval, and audit tests | P2-S4-04 |

---

# 7. Phase 3 - Advanced ExecutionView Engine

## 7.1 Sprint 5 - Parent-child order model and route strategy parity

### Sprint objective
Create the execution data model required for algorithmic scheduling and remove route-create/route-modify feature asymmetry.

### Sprint dependencies
- Phase 2 complete

### Sprint 5 issue list

#### Issue P3-S5-01 - Introduce parent-child execution models
- **Depends on**: Phase 2
- **Acceptance**:
  - parent order objective and child route state are persistable and queryable

#### Issue P3-S5-02 - Make route creation support strategy parameters and broker algo payloads
- **Depends on**: P3-S5-01
- **Acceptance**:
  - create-route supports same strategy payload class as modify-route where EMSX allows it

#### Issue P3-S5-03 - Surface parent-child views in frontend types and tables
- **Depends on**: P3-S5-01, P3-S5-02
- **Acceptance**:
  - order and route tables show parent/child execution context and schedule state

#### Issue P3-S5-04 - Add command and schema tests for parent-child flows
- **Depends on**: P3-S5-01, P3-S5-02, P3-S5-03
- **Acceptance**:
  - parent-child creation, validation, and rendering paths are test-covered

### Sprint 5 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/models/parent_child_orders.py` | create | Define parent/child execution entities | Parent execution objective, child schedule, participation state, benchmark metadata | P3-S5-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/repositories/parent_child_repository.py` | create | Persist parent-child execution records | CRUD/query helpers by parent order, child route, schedule state | P3-S5-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/route_service.py` | create | Own route creation/modify business logic | Unify route creation and modification strategy param handling | P3-S5-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/execution_commands.py` | update | Delegate route creation to route service | Keep compatibility with current request contracts while extending payloads | P3-S5-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/routes.py` | update | Expose richer route create payloads | Add validation rules, model versioning, and error shaping | P3-S5-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/migrations/002_parent_child_execution.sql` | create | Create parent-child execution schema | Tables for parent objectives, child slices, schedule checkpoints, benchmark fields | P3-S5-01 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/types/index.ts` | update | Add parent-child and benchmark types | Parent execution objective, child slice state, benchmark schedule fields | P3-S5-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/order-route-dialog.tsx` | update | Support strategy payloads at route creation time | Use same broker strategy field model as route modify dialogs | P3-S5-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/route-modify-dialogs.tsx` | update | Reuse unified strategy payload model | Normalize request contracts for create/modify parity | P3-S5-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/OrderTable.tsx` | update | Display parent execution metadata | Add benchmark objective, schedule status, child-count indicators | P3-S5-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/RouteTable.tsx` | update | Display child route context | Add parent objective, slice state, benchmark progress, child errors | P3-S5-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_parent_child_execution.py` | create | Validate parent-child persistence and command flows | Test schedule metadata, strategy params, route create/modify symmetry | P3-S5-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/order-route-dialog.test.tsx` | create | Validate strategy-aware route creation UI | Mock strategy loading and verify payload shape | P3-S5-04 |

---

## 7.2 Sprint 6 - Benchmark execution scheduler

### Sprint objective
Deliver the first algorithmic scheduling engine for TWAP, VWAP, and participation-based execution.

### Sprint dependencies
- Sprint 5 complete

### Sprint 6 issue list

#### Issue P3-S6-01 - Build benchmark scheduling engine
- **Depends on**: Sprint 5
- **Acceptance**:
  - scheduler can generate child slices for TWAP/VWAP/POV objectives

#### Issue P3-S6-02 - Add runtime scheduler orchestration and pause/resume controls
- **Depends on**: P3-S6-01
- **Acceptance**:
  - parents can be started, paused, resumed, and cancelled without orphan slices

#### Issue P3-S6-03 - Add frontend controls for algorithmic execution launch and monitoring
- **Depends on**: P3-S6-01, P3-S6-02
- **Acceptance**:
  - traders can launch benchmark executions and observe drift/progress

#### Issue P3-S6-04 - Add benchmark engine tests and performance baselines
- **Depends on**: P3-S6-01, P3-S6-02
- **Acceptance**:
  - benchmark scheduling logic has deterministic tests and performance thresholds

### Sprint 6 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/benchmark_engine.py` | create | Compute TWAP/VWAP/POV schedules | Produce slice schedule from parent objective, market profile, and remaining quantity | P3-S6-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/algo_scheduler.py` | create | Runtime scheduler and state transitions | Tick-based or event-triggered orchestration, pause/resume, drift checks, child submission | P3-S6-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/projection_service.py` | update | Persist schedule progress and drift state | Store benchmark progress, participation error, schedule status in parent/child projections | P3-S6-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/orders.py` | update | Add parent execution launch/control endpoints | Endpoints for create/start/pause/resume/cancel algorithmic parents | P3-S6-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/algo-launch-dialog.tsx` | create | UI for benchmark execution launch | Form for strategy type, urgency, schedule horizon, participation cap, fallback rules | P3-S6-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/ExecutionBoard.tsx` | update | Add algo launch/monitoring surface | Launch control, schedule status panel, benchmark progress summary | P3-S6-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/RouteTable.tsx` | update | Show slice progress and drift | Add per-child schedule timing and fill progression columns | P3-S6-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/types/index.ts` | update | Add benchmark control request/response types | Parent launch, pause/resume, drift metrics, schedule status types | P3-S6-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_benchmark_engine.py` | create | Validate schedule generation | Golden tests for TWAP/VWAP/POV schedules and drift thresholds | P3-S6-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_algo_scheduler.py` | create | Validate runtime scheduling orchestration | Pause/resume/cancel, child submission sequencing, schedule completion tests | P3-S6-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/algo-launch-dialog.test.tsx` | create | Validate benchmark launch UI | Form validation and request-shape tests | P3-S6-04 |

---

# 8. Phase 4 - CostView Closed Loop

## 8.1 Sprint 7 - Fill linkage and TCA foundation

### Sprint objective
Link execution data to fills and establish the initial benchmark/TCA pipeline.

### Sprint dependencies
- Phase 3 complete

### Sprint 7 issue list

#### Issue P4-S7-01 - Normalize fill ingestion linkage keys
- **Depends on**: Phase 3
- **Acceptance**:
  - fills map reliably to parent order, child route, trader, and broker identifiers

#### Issue P4-S7-02 - Add benchmark and slippage calculation foundation
- **Depends on**: P4-S7-01
- **Acceptance**:
  - arrival/VWAP/TWAP benchmark calculations exist for linked fills

#### Issue P4-S7-03 - Export execution state to analytics layer
- **Depends on**: P4-S7-01
- **Acceptance**:
  - execution service emits analytics-ready datasets for CostView consumption

#### Issue P4-S7-04 - Add TCA integration tests
- **Depends on**: P4-S7-02, P4-S7-03
- **Acceptance**:
  - sample execution set can be linked end-to-end to fill and benchmark outputs

### Sprint 7 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/CostView/src/benchmark_engine.py` | create | Compute TCA benchmarks | Arrival price, market VWAP, TWAP reconstruction, participation benchmarks | P4-S7-02 |
| `c:/Users/hrchen/Documents/EMSX/CostView/src/slippage_analysis.py` | create | Compute slippage and shortfall metrics | Implementation shortfall, benchmark slippage, timing and impact decomposition | P4-S7-02 |
| `c:/Users/hrchen/Documents/EMSX/CostView/src/fill_linker.py` | create | Link fills to execution entities | Resolve fills to orders/routes/parents using UUIDs, sequence, route IDs, timestamps | P4-S7-01 |
| `c:/Users/hrchen/Documents/EMSX/CostView/src/pipeline.py` | update | Add linked execution analytics stage | Insert fill linking and benchmark/slippage stages into pipeline | P4-S7-03 |
| `c:/Users/hrchen/Documents/EMSX/CostView/src/raw_fills_db.py` | update | Store linkage metadata | Add columns/indexes for route and parent execution IDs | P4-S7-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/analytics_export.py` | create | Publish execution snapshots to CostView | Export parent-child schedule, route, benchmark, and audit context | P4-S7-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/fill_linking_service.py` | create | Provide canonical linkage lookup API | Query helper for route/order/benchmark identity resolution | P4-S7-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/config.py` | update | Expose benchmark metadata where needed | Provide config/metadata required by CostView calculations | P4-S7-03 |
| `c:/Users/hrchen/Documents/EMSX/CostView/tests/test_fill_linker.py` | create | Validate fill-to-route linking | Fixture-based tests for exact, fuzzy, and missing-link scenarios | P4-S7-04 |
| `c:/Users/hrchen/Documents/EMSX/CostView/tests/test_benchmark_engine.py` | create | Validate benchmark calculations | Deterministic benchmark outputs for sample fills and intraday profiles | P4-S7-04 |

---

## 8.2 Sprint 8 - Scorecards and execution feedback loop

### Sprint objective
Turn TCA outputs into broker, strategy, and trader feedback for the execution platform.

### Sprint dependencies
- Sprint 7 complete

### Sprint 8 issue list

#### Issue P4-S8-01 - Build broker/strategy/trader scorecards
- **Depends on**: Sprint 7
- **Acceptance**:
  - scorecards aggregate execution quality by broker, strategy, symbol bucket, and trader

#### Issue P4-S8-02 - Publish feedback into execution control plane
- **Depends on**: P4-S8-01
- **Acceptance**:
  - execution platform can query scorecard outputs and annotate routing choices

#### Issue P4-S8-03 - Surface TCA and scorecards in frontend
- **Depends on**: P4-S8-01, P4-S8-02
- **Acceptance**:
  - settings/monitoring surfaces expose benchmark and scorecard summaries

#### Issue P4-S8-04 - Add E2E feedback-loop verification
- **Depends on**: P4-S8-02, P4-S8-03
- **Acceptance**:
  - test proves a completed execution affects future routing metadata display

### Sprint 8 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/CostView/src/broker_scorecards.py` | create | Aggregate broker and strategy performance | Daily and rolling-window scorecards with liquidity bucket and market regime slices | P4-S8-01 |
| `c:/Users/hrchen/Documents/EMSX/CostView/src/execution_feedback.py` | create | Publish ranked execution feedback | Emit recommendation-ready metrics to backend config/analytics endpoints | P4-S8-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/config_service.py` | update | Ingest performance feedback into control plane | Store scorecard versions and expose latest approved ranking inputs | P4-S8-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/analytics_export.py` | update | Add scorecard retrieval endpoints or feeds | Provide broker/strategy/trader performance summaries to frontend | P4-S8-02 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/SettingsBoard.tsx` | update | Show scorecards and config impact | Add broker scorecard panels, effective default strategy hints, refresh status | P4-S8-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/MonitorBoard.tsx` | update | Add execution quality views | Add slippage/watchlist panels and poor-performing strategy highlights | P4-S8-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/api.ts` | update | Add scorecard endpoints | Fetch broker/strategy/trader scorecards and feedback metadata | P4-S8-03 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/types/index.ts` | update | Add scorecard data contracts | Broker scorecard, strategy scorecard, and feedback ranking types | P4-S8-03 |
| `c:/Users/hrchen/Documents/EMSX/CostView/tests/test_broker_scorecards.py` | create | Validate scorecard aggregation | Test grouping, rolling windows, and outlier handling | P4-S8-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_feedback_integration.py` | create | Validate CostView-to-ExecutionView feedback path | Ensure feedback versions are retrievable and mapped into config/control plane | P4-S8-04 |

---

# 9. Phase 5 - Intelligence Layer

## 9.1 Sprint 9 - CEP surveillance, replay, and recommendation framework

### Sprint objective
Add event-driven surveillance, replay, and recommendation scaffolding on top of the closed-loop platform.

### Sprint dependencies
- Phase 4 complete

### Sprint 9 issue list

#### Issue P5-S9-01 - Build CEP event pattern engine
- **Depends on**: Phase 4
- **Acceptance**:
  - stale-order, slippage drift, and broker degradation events are inferable from streams

#### Issue P5-S9-02 - Add event replay service
- **Depends on**: P5-S9-01
- **Acceptance**:
  - one execution day can be replayed against historical events and projections

#### Issue P5-S9-03 - Add recommendation framework seeded by scorecards
- **Depends on**: P4-S8-01, P5-S9-01
- **Acceptance**:
  - recommendation output is explainable and references scorecard + regime inputs

#### Issue P5-S9-04 - Surface intelligence features in UI and QA them
- **Depends on**: P5-S9-01, P5-S9-02, P5-S9-03
- **Acceptance**:
  - monitor board and execution launch surfaces show CEP alerts, replay controls, and recommendations

### Sprint 9 file change specification

| File Path | Type | Purpose | Technical Implementation Details | Depends On |
|---|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/cep_engine.py` | create | Detect complex execution events | Rules for stale orders, abnormal drift, broker degradation, missed participation windows | P5-S9-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/risk_rules.py` | create | Encapsulate execution surveillance rules | Declarative rule registry with thresholds and severity mapping | P5-S9-01 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/replay_service.py` | create | Replay event history | Rebuild projections from event/audit history with time control and scenario selection | P5-S9-02 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/services/broker_recommendation.py` | create | Rank brokers/strategies for future executions | Combine scorecards, liquidity regime, benchmark objective, and policy constraints | P5-S9-03 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/routers/realtime.py` | update | Expose CEP/replay channels | Add alert stream and replay stream/session controls | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/sections/MonitorBoard.tsx` | update | Display CEP alerts and event clusters | Add alert severity, suppression, acknowledgment, and drill-down views | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/replay-console.tsx` | create | UI for historical replay | Replay selection, speed control, point-in-time navigation, event inspection | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/recommendation-panel.tsx` | create | Show broker/strategy recommendations | Explainable ranking panel with metric provenance | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/algo-launch-dialog.tsx` | update | Consume recommendation output | Pre-populate launch defaults and explain recommended broker/strategy | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/services/realtime.ts` | update | Support alert and replay channels | Multi-channel subscription support, replay session control events | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_cep_engine.py` | create | Validate event-pattern inference | Rule evaluation tests across order/route/fill/adverse-drift scenarios | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_replay_service.py` | create | Validate deterministic replay | Replay from event history and compare output projection states | P5-S9-04 |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/components/recommendation-panel.test.tsx` | create | Validate explainable recommendation display | Verify ranking rationale and fallback states | P5-S9-04 |

---

# 10. Cross-cutting quality assurance plan

## 10.1 Backend QA stack

### Files to add/update across phases

| File Path | Type | Purpose | Technical Implementation Details |
|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/backend/api/pytest.ini` | create | Central pytest config | Markers for unit/integration/replay/perf tests |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/conftest.py` | create | Shared backend fixtures | DB fixture, mocked Bloomberg sessions, event fixtures |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_api_smoke.py` | create | API smoke coverage | Minimal end-to-end tests for health, orders, routes, auth, realtime |
| `c:/Users/hrchen/Documents/EMSX/backend/api/tests/test_perf_thresholds.py` | create | Performance regression guard | Validate query latency and scheduling performance budgets |

## 10.2 Frontend QA stack

| File Path | Type | Purpose | Technical Implementation Details |
|---|---|---|---|
| `c:/Users/hrchen/Documents/EMSX/frontend/vitest.config.ts` | create | Frontend test config | React/Vite test runner with jsdom and alias support |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/test/setup.ts` | create | Shared frontend test setup | Mock browser APIs, WS, notifications, localStorage |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/test/msw/server.ts` | create | API mocking infrastructure | Mock REST bootstrap and delta bootstrap flows |
| `c:/Users/hrchen/Documents/EMSX/frontend/src/test/render-app.tsx` | create | Shared render helper | Providers, caches, and session stubs |

## 10.3 Workflow QA gates

- CI blocks merge when:
  - backend tests fail
  - frontend tests fail
  - lint/typecheck fails
  - migration files and ORM models diverge
  - sprint ledger is not updated for merged sprint issues
- Release gate blocks sprint completion when:
  - risk register has unowned critical items
  - handoff summary is missing
  - architecture decision updates are required but absent

---

# 11. Dependency map

## 11.1 Phase dependencies

- **Phase 0 -> Phase 1**: workflow automation, CI gates, sprint ledger must exist first
- **Phase 1 -> Phase 2**: durable projections and realtime path must exist before refactor extraction
- **Phase 2 -> Phase 3**: service boundaries and config/policy model must exist before algo engine work
- **Phase 3 -> Phase 4**: parent-child execution model must exist before CostView linkage
- **Phase 4 -> Phase 5**: TCA and scorecards must exist before recommendations are trusted

## 11.2 Critical file relationships

- `backend/api/main.py` -> progressively reduced into composition root
- `backend/api/Dockerfile` must change early because new backend modules will not be copied otherwise
- `frontend/src/App.tsx` should only be simplified after `services/realtime.ts` and stream hooks exist
- `frontend/src/types/index.ts` must be updated in every phase that changes backend models
- `CostView/src/pipeline.py` depends on stable execution export contracts from `backend/api/services/analytics_export.py`
- `plans/execution-platform-status.yaml` must be updated in every sprint as the source of truth for progress automation

---

# 12. Progress monitoring model

## 12.1 Required metrics

Track these in `c:/Users/hrchen/Documents/EMSX/.workbuddy/knowledge/metrics.md`:

- current phase
- current sprint
- planned vs completed issues
- lead time per issue
- checkpoint pass/fail counts
- escaped defects by sprint
- p95 order-query latency
- p95 event-to-screen latency
- benchmark scheduler decision latency
- TCA linkage completeness

## 12.2 Status update flow

1. Developer updates issue state in branch/PR.
2. CI runs.
3. `sync_execution_status.py` updates:
   - sprint ledger
   - iteration log
   - metrics
4. daily automation captures status into handoff.
5. phase gate validator approves or blocks sprint closure.

---

# 13. Definition of done by phase

## Phase 0 done
- Workflow artifacts exist and are auto-updated.
- CI and PR templates enforce checkpoints.

## Phase 1 done
- Orders/routes/audit are durably persisted.
- Realtime path is live and UI is stream-first.

## Phase 2 done
- `main.py` is a composition root, not a monolith.
- Auth/policy/config responsibilities are modular.

## Phase 3 done
- Parent-child benchmark execution flows are operational.
- Route creation/modify parity exists for strategy payloads.

## Phase 4 done
- CostView produces linked TCA and feedback scorecards.
- ExecutionView platform consumes scorecard outputs.

## Phase 5 done
- CEP alerts, replay, and explainable recommendations are available.
- Intelligence layer is grounded in real TCA feedback, not static rules alone.

---

# 14. Recommended execution order

1. Execute **Sprint 0** first and do not skip it.
2. Complete **Sprint 1** and **Sprint 2** before any major service extraction.
3. Only begin **Sprint 5** after config/auth/policy boundaries stabilize in **Sprint 4**.
4. Start **Sprint 7** only after parent-child execution IDs are stable.
5. Treat **Sprint 9** as enablement, not MVP scope.

---

# 15. Immediate next actions

1. Approve this WBS as the planning baseline.
2. Implement Sprint 0 workflow artifacts.
3. Open issues for Sprint 1 using the new issue template.
4. Create a branch for `phase-1/sprint-1` after Sprint 0 gate passes.

---

# 16. Notes for maintainers

- The highest structural-risk file remains `c:/Users/hrchen/Documents/EMSX/backend/api/main.py`.
- The earliest packaging-risk file is `c:/Users/hrchen/Documents/EMSX/backend/api/Dockerfile`, because it currently copies only `main.py` and `auth.py`.
- The highest continuity-risk area is fragmented state across backend memory, JSON files, and frontend `localStorage`; Sprint 1 and Sprint 4 address that directly.
- The recommendation layer must not be promoted to production decisioning until Phase 4 scorecards are stable and validated.

