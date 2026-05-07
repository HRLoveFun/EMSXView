# EMSX Logical Data Domain

> Boundary definition for shared platform data
> Last updated: 2026-05-07

---

## Purpose

This document defines the repository's logical data domain.

The goal is not to force every workload into one database or one package. The goal is to make ownership, access paths, and integration contracts explicit.

---

## Principles

1. One logical data domain does not imply one physical database.
2. ExecutionView owns operational state.
3. CostView owns analytical and pipeline data.
4. Cross-domain access should go through adapters or documented services.
5. Storage decisions must follow workload shape, not diagram aesthetics.

---

## Data subdomains

### 1. ExecutionView operational state

Examples:

- live order projections
- live route projections
- operational audit events
- persistence for restart and warm-start

Primary code surfaces:

- `ExecutionView/backend/api/db.py`
- `ExecutionView/backend/api/service_provider.py`
- `ExecutionView/backend/api/repositories/`
- `ExecutionView/backend/api/models/`

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
- `CostView/src/db/repositories/market_data_read.py`
- `CostView/src/db/repositories/market_data_write.py`
- `CostView/src/daily_metrics_calculator.py`

Deprecated surfaces (retained for pipeline migration):

- `CostView/src/raw_bdib_db.py` → use `db/repositories/market_data_*`
- `CostView/src/fill_bdib_db.py` → use `db/repositories/integrated`

### 3. Fill and execution-history data

Examples:

- raw fills
- cleaned fills
- processed fills
- fill aggregation results

Primary code surfaces:

- `CostView/src/fill_fetch.py`
- `CostView/src/db/repositories/fills_read.py`
- `CostView/src/db/repositories/fills_write.py`
- `CostView/src/db/repositories/raw_fills_read.py`
- `CostView/src/db/repositories/raw_fills_write.py`

Deprecated surfaces (retained for pipeline migration):

- `CostView/src/raw_fills_db.py` → use `db/repositories/raw_fills_*`
- `CostView/src/processed_fills_db/` → use `db/repositories/fills_*`

### 4. Analytical query and reporting data

Examples:

- TCA order summaries
- route-level benchmark metrics
- price/volume dynamics series
- analytical warning states
- regime distribution and classification

Primary code surfaces:

- `CostView/src/tca_query_service.py`
- `CostView/src/db/repositories/regime.py`
- `ExecutionView/backend/api/routers/costview.py`

Canonical shared adapters:

- `platform_data.build_platform_data_access().analytics`
- `platform_data.build_platform_data_access().database`

---

## Contract layer

Cross-module data contracts are defined in `platform_data/contracts/`. This is the **only legal source** for data types and constants that cross module boundaries (ExecutionView ↔ CostView ↔ MarketView).

Current contracts:

- `platform_data/contracts/fill_contracts.py` — `SCORECARD_COHORTS` tuple
- `platform_data/contracts/market_data_contracts.py` — (placeholder for future market data types)
- `platform_data/contracts/regime_contracts.py` — (placeholder for future regime types)

Rule: Consumers import from `platform_data.contracts`, not from `CostView.src.*` directly.

---

## Adapter entry

The shared code entry is:

- `platform_data/__init__.py`
- `platform_data/adapters.py`
- `platform_data/contracts/`
- `platform_data/repositories.py`

Current adapters:

- `ExecutionOperationalDataAdapter` — live execution state
- `MarketReferenceDataAdapter` — market snapshots and intraday features
- `CostViewAnalyticsAdapter` — TCA and scorecard reports
- `CostViewDatabaseAdapter` — read-only regime/fills/market data queries via `CostViewDatabase`
- `ExecutionHistoryAdapter` — fill/order/route history
- `HandoffExchangeAdapter` — cross-module handoff contracts
- `PlatformDataAccess` — unified entry point holding all adapters

Example:

```python
from platform_data import build_platform_data_access
from platform_data.contracts import SCORECARD_COHORTS

platform_data = build_platform_data_access(repository_provider=repo_provider)
orders = await platform_data.operational.load_orders(limit=100)
snapshot = platform_data.market.get_market_snapshot(limit=25)
report = platform_data.analytics.build_tca_report(filters)
regime_rows = platform_data.database.get_regime_distribution(start_date, end_date)
```

---

## Current ownership boundary

ExecutionView may read or persist operational state through its provider-backed adapter.

CostView may build analytical reports and pipeline outputs through its analytics adapter.

ExecutionView should not treat CostView internals as its default persistence layer.

CostView should not treat ExecutionView's operational projection store as its analytical warehouse.

---

## Near-term migration path

1. Move new cross-domain callers to `platform_data/` first.
2. Cross-module deep imports from ExecutionView to CostView have been eliminated; `platform_data/contracts/` is the canonical source for shared constants.
3. Legacy CostView DB classes (`raw_fills_db.py` etc.) are deprecated; `pipeline.py` and `MigrationManager` still reference them — full migration to `db/` subsystem is pending.
4. Add more contracts and adapters only when a real caller needs them (YAGNI).
5. Defer any storage unification until there is a workload-driven reason.

---

## Non-goals

- No immediate rewrite into a single monorepo Python package layout.
- No immediate migration of SQLite analytical stores into PostgreSQL.
- No immediate removal of the existing CostView pipeline boundaries.

---

## Decision summary

The platform now treats data as one logical domain with multiple owned subdomains, unified by adapters and documentation rather than by forced physical consolidation.