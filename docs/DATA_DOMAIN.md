# EMSX Logical Data Domain

> Boundary definition for shared platform data
> Last updated: 2026-04-22

---

## Purpose

This document defines the repository's logical data domain.

The goal is not to force every workload into one database or one package. The goal is to make ownership, access paths, and integration contracts explicit.

---

## Principles

1. One logical data domain does not imply one physical database.
2. Execution owns operational state.
3. CostView owns analytical and pipeline data.
4. Cross-domain access should go through adapters or documented services.
5. Storage decisions must follow workload shape, not diagram aesthetics.

---

## Data subdomains

### 1. Execution operational state

Examples:

- live order projections
- live route projections
- operational audit events
- persistence for restart and warm-start

Primary code surfaces:

- `Execution/backend/api/db.py`
- `Execution/backend/api/service_provider.py`
- `Execution/backend/api/repositories/`
- `Execution/backend/api/models/`

Canonical shared adapter:

- `platform_data.build_platform_data_access(repository_provider=...).operational`

### 2. Market reference and market-history data

Examples:

- BDIB bars
- daily summary metrics
- exchange-local time alignment inputs
- future MarketView pre-trade market context

Primary code surfaces:

- `CostView/src/bdib_fetcher.py`
- `CostView/src/raw_bdib_db.py`
- `CostView/src/fill_bdib_db.py`
- `CostView/src/daily_metrics_calculator.py`

### 3. Fill and execution-history data

Examples:

- raw fills
- cleaned fills
- processed fills
- fill aggregation results

Primary code surfaces:

- `CostView/src/fill_fetch.py`
- `CostView/src/raw_fills_db.py`
- `CostView/src/processed_fills_db.py`
- `CostView/src/fill_processor.py`
- `CostView/src/fill_aggregator.py`

### 4. Analytical query and reporting data

Examples:

- TCA order summaries
- route-level benchmark metrics
- price/volume dynamics series
- analytical warning states

Primary code surfaces:

- `CostView/src/tca_query_service.py`
- `Execution/backend/api/routers/costview.py`

Canonical shared adapter:

- `platform_data.build_platform_data_access().analytics`

---

## Adapter entry

The shared code entry is:

- `platform_data/__init__.py`
- `platform_data/adapters.py`

Current adapters:

- `ExecutionOperationalDataAdapter`
- `MarketReferenceDataAdapter`
- `CostViewAnalyticsAdapter`
- `PlatformDataAccess`

Example:

```python
from platform_data import build_platform_data_access

platform_data = build_platform_data_access(repository_provider=repo_provider)
orders = await platform_data.operational.load_orders(limit=100)
snapshot = platform_data.market.get_market_snapshot(limit=25)
report = platform_data.analytics.build_tca_report(filters)
```

---

## Current ownership boundary

Execution may read or persist operational state through its provider-backed adapter.

CostView may build analytical reports and pipeline outputs through its analytics adapter.

Execution should not treat CostView internals as its default persistence layer.

CostView should not treat Execution's operational projection store as its analytical warehouse.

---

## Near-term migration path

1. Move new cross-domain callers to `platform_data/` first.
2. Leave existing direct deep imports in place unless the change is low-risk and local.
3. Add more adapters only when a real caller needs them.
4. Defer any storage unification until there is a workload-driven reason.

---

## Non-goals

- No immediate rewrite into a single monorepo Python package layout.
- No immediate migration of SQLite analytical stores into PostgreSQL.
- No immediate removal of the existing CostView pipeline boundaries.

---

## Decision summary

The platform now treats data as one logical domain with multiple owned subdomains, unified by adapters and documentation rather than by forced physical consolidation.