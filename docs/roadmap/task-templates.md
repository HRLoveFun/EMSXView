# Execution Platform Task Templates

> Last updated: 2026-05-07 | Reference — detailed task definitions, see docs/roadmap/wbs.md

See docs/dev-guide.md §2 for current project facts ("current surface" refers to active implementation areas, not legacy).

---

## WBS-01 — Shared Contract & Platform Data Access

> Establish the canonical shared contract across frontend/ (App.tsx), backend/ (main.py), platform_data/adapters.py, and CostView/src/. Define the execution history spine, shared contracts for market reference / live execution / execution history / analytics, and make execution history the cross-module authority.

**Affected files**: platform_data/adapters.py · service_provider.py · schemas.py · docs/spec/data-domain.md

**Test**: python -m pytest tests/test_platform_data_access.py tests/test_service_provider.py tests/test_db_bootstrap.py tests/test_projection_repositories.py -q

---

## WBS-02 — ExecutionView Bloomberg Adapter Layer

> Refactor services/bloomberg_adapter.py into proper abstraction layers: session manager, blotter projector, command service, market/refdata enrichment, and startup status service.

**Affected files**: services/bloomberg_adapter.py · bloomberg_interface.py · realtime_gateway.py · routers/connection.py · routers/realtime.py

**Test**: python -m pytest tests/test_bloomberg_adapter_refdata.py tests/test_connection_router.py tests/test_realtime_gateway.py -q

---

## WBS-03 — EMSX Route Management & Broker Strategy Catalog

> Implement RouteEx/ModifyRouteEx/CancelRouteEx with proper error handling, reset and strategy parameter support. Build broker / asset class / strategy / field order catalog in services/route_service.py.

**Affected files**: services/route_service.py · bloomberg_adapter.py · routers/orders.py · routers/routes.py · routers/broker.py · schemas.py · types/index.ts

**Test**: python -m pytest tests/test_bloomberg_adapter_routing.py tests/test_parent_child_execution.py -q + npm run build

---

## WBS-04 — MarketView Snapshot Integration

> Connect MarketView module to bdib_daily_summary data via the shared contract. Build the MarketView snapshot API and frontend anchor.

**Affected files**: modules/marketview/ · routers/marketview.py · platform_data/adapters.py

**Test**: python -m pytest tests/test_platform_data_access.py -q + npm run build + smoke test /api/marketview/snapshot

---

## WBS-05 — MarketView Intraday Feature Service

> Add BDIB intraday feature service to MarketView, extending from the daily summary foundation. Build realtime-capable intraday data service alongside existing daily aggregation.

**Affected files**: CostView/src/raw_bdib_db.py · pipeline.py · daily_metrics_calculator.py · platform_data/adapters.py · routers/marketview.py

**Test**: python -m pytest tests/test_tca_query_service.py test_pipeline_guards.py -q + npm run build

---

## WBS-06 — CostView Fill Pipeline & History Linkage

> Transform CostView from a fill-centric pipeline to an execution-history-aware system. Link fills with order/route/event data to enable proper TCA lineage.

**Affected files**: emsx_client.py · fill_fetch.py · pipeline.py · tca_query_service.py · backend/api/service_provider.py

**Test**: python -m pytest tests/test_fill_fetch.py tests/test_tca_query_service.py test_pipeline_guards.py -q + pytest tests/test_service_provider.py tests/test_db_bootstrap.py -q

---

## WBS-07 — CostView TCA Scorecard

> Build the CostView TCA scorecard layer on top of the execution history spine. Surface scorecard metrics through the CostView frontend module.

**Affected files**: CostView/src/tca_query_service.py · frontend/modules/costview/ · platform_data/adapters.py

**Test**: pytest tests/test_tca_query_service.py test_pipeline_guards.py -q + npm run build && npm test

---

## WBS-08 — Cross-Module Handoff Contracts

> Formalize handoff contracts between all three modules: MarketView ↔ ExecutionView, ExecutionView ↔ CostView, CostView ↔ ExecutionView (broker/strategy feedback).

**Affected files**: App.tsx · WorkspaceModuleTabs.tsx · platform_data/adapters.py · routers/marketview/orders/broker/costview.py

**Test**: pytest tests/test_platform_data_access.py tests/test_connection_router.py -q + npm run build && npm test + API smoke test

---

## Dependency Order

1. WBS-01 (shared contract foundation)
2. WBS-02 + WBS-04 (parallel, depend on WBS-01)
3. WBS-03 (depends on WBS-02)
4. WBS-05 (depends on WBS-04)
5. WBS-06 (depends on WBS-01)
6. WBS-07 (depends on WBS-06)
7. WBS-08 (depends on all previous WBS)
