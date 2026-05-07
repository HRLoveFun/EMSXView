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
3. CostView owns algorithm evaluation and analytical concerns.
4. Data acquisition, processing, and storage is an independent infrastructural subdomain, separate from any single analytical workload.
5. Cross-domain access should go through adapters or documented services.
6. Storage decisions must follow workload shape, not diagram aesthetics.

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

### 2. Data platform — acquisition, processing, and storage (independent subsystem)

> Data ingestion, cleaning, enrichment, metrics computation, and pipeline orchestration.
> This subdomain is owned by an independent Data Platform subsystem, **not** by CostView.

Examples:

- raw fills ingestion, deduplication, and enrichment
- fill cleaning and processing pipeline
- BDIB bar acquisition and storage
- daily summary metrics computation
- pipeline orchestration and migration management
- data quality monitoring

Primary code surfaces (target — see Near-term migration path):

- `DataPipeline/src/ingestion/` — fill and market data ingestion
- `DataPipeline/src/processing/` — cleaning, enrichment, metrics
- `DataPipeline/src/storage/` — repository layer for processed data
- `DataPipeline/src/orchestration/` — pipeline and migration management

Legacy surfaces (currently in `CostView/src/`, awaiting extraction):

- `CostView/src/fill_fetch.py` → migrate to `DataPipeline/src/ingestion/`
- `CostView/src/fill_ingestion.py` → migrate to `DataPipeline/src/ingestion/`
- `CostView/src/fill_cleaner.py` → migrate to `DataPipeline/src/processing/`
- `CostView/src/fill_processor.py` → migrate to `DataPipeline/src/processing/`
- `CostView/src/fill_aggregator.py` → migrate to `DataPipeline/src/processing/`
- `CostView/src/bdib_fetcher.py` → migrate to `DataPipeline/src/acquisition/`
- `CostView/src/daily_metrics_calculator.py` → migrate to `DataPipeline/src/processing/`
- `CostView/src/pipeline.py` → migrate to `DataPipeline/src/orchestration/`
- `CostView/src/raw_fills_db.py` → migrate to `DataPipeline/src/storage/`
- `CostView/src/raw_bdib_db.py` → migrate to `DataPipeline/src/storage/`
- `CostView/src/processed_fills_db/` → migrate to `DataPipeline/src/storage/`
- `CostView/src/db/repositories/raw_fills_*` → migrate to `DataPipeline/src/storage/`
- `CostView/src/db/repositories/fills_*` → migrate to `DataPipeline/src/storage/`
- `CostView/src/db/repositories/market_data_*` → migrate to `DataPipeline/src/storage/`
- `CostView/src/db/repositories/integrated.py` → migrate to `DataPipeline/src/storage/`

Canonical shared adapter:

- `platform_data.build_platform_data_access().data_platform` (planned)

### 3. CostView — algorithm evaluation and analytics (refocused)

> CostView loads algorithm evaluation models, invokes data from the Data Platform,
> and produces evaluation results. It no longer owns data acquisition or processing.

Examples:

- algorithm evaluation model registry and lifecycle
- model-driven TCA and scorecard computation
- route-level benchmark evaluation
- price/volume dynamics series
- regime distribution and classification
- analytical warning states
- evaluation output reporting

Primary code surfaces:

- `CostView/src/tca_query_service.py` — TCA and scorecard query
- `CostView/src/evaluation/` — model loading and evaluation orchestration (new)
- `CostView/src/models/` — algorithm evaluation model definitions (new)
- `CostView/src/attribution/` — performance attribution
- `CostView/src/regime/` — regime classification and analysis
- `CostView/src/db/repositories/regime.py` — regime query repository
- `CostView/src/execution_history_service.py` — execution history read path
- `ExecutionView/backend/api/routers/costview.py` — API surface

Canonical shared adapters:

- `platform_data.build_platform_data_access().analytics`
- `platform_data.build_platform_data_access().database`
- `platform_data.build_platform_data_access().execution_history`

### 4. MarketView — pre-trade market context (placeholder)

> Reserved for future MarketView pre-trade market context data.
> Market reference data (BDIB, daily summary) is owned by the Data Platform
> subdomain and consumed by MarketView through adapters.

---

## Contract layer

Cross-module data contracts are defined in `platform_data/contracts/`. This is the **only legal source** for data types and constants that cross module boundaries (ExecutionView â†” CostView â†” MarketView).

Current contracts:

- `platform_data/contracts/fill_contracts.py` â€” `SCORECARD_COHORTS` tuple
- `platform_data/contracts/market_data_contracts.py` â€” (placeholder for future market data types)
- `platform_data/contracts/regime_contracts.py` — (placeholder for future regime types)
- `platform_data/contracts/data_platform_contracts.py` — (planned — ingestion config, pipeline state, processing schemas)
- `platform_data/contracts/evaluation_contracts.py` — (planned — algorithm model metadata, evaluation specs, output format)

Rule: Consumers import from `platform_data.contracts`, not from `CostView.src.*` directly.

---

## Adapter entry

The shared code entry is:

- `platform_data/__init__.py`
- `platform_data/adapters.py`
- `platform_data/contracts/`
- `platform_data/repositories.py`

Current adapters:

- `ExecutionOperationalDataAdapter` \â€\” live execution state (owner: ExecutionView)
- `MarketReferenceDataAdapter` \â€\” market snapshots and intraday features (owner: Data Platform, consumed by MarketView/CostView)
- `CostViewAnalyticsAdapter` \â€\” TCA and scorecard reports (owner: CostView)
- `CostViewDatabaseAdapter` \â€\” read-only database queries via `CostViewDatabase` (owner: CostView)
- `ExecutionHistoryAdapter` \â€\” fill/order/route history (owner: Data Platform, consumed by CostView)
- `HandoffExchangeAdapter` \â€\” cross-module handoff contracts (owner: platform_data)
- `PlatformDataAccess` \â€\” unified entry point holding all adapters

Planned adapters:

- `DataPlatformIngestionAdapter` \â€\” ingestion trigger and pipeline status (planned)
- `AlgorithmEvaluationAdapter` \â€\” model-driven evaluation output (planned)

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

CostView may build analytical reports and evaluation outputs through its analytics adapter.
CostView loads algorithm evaluation models and processes data sourced from the Data Platform;
it does **not** own data ingestion, cleaning, or storage infrastructure.

Data Platform owns all data acquisition, processing, and storage surfaces.
It exposes data through canonical adapters for consumption by CostView, MarketView,
and ExecutionView. No analytical workload should bypass the Data Platform to
access raw storage.

ExecutionView should not treat CostView internals as its default persistence layer.

CostView should not treat ExecutionView's operational projection store as its analytical warehouse.

Data Platform should not embed domain-specific analytical logic — its responsibility
ends at clean, well-structured data delivery.

---

## Near-term migration path

1. **Extract Data Platform subdomain.** Create `DataPipeline/` package and migrate the following from `CostView/src/`:
   - Ingestion: `fill_fetch.py`, `fill_ingestion.py`, `bdib_fetcher.py`
   - Processing: `fill_cleaner.py`, `fill_processor.py`, `fill_aggregator.py`, `daily_metrics_calculator.py`, `pipeline.py`
   - Storage: `raw_fills_db.py`, `raw_bdib_db.py`, `processed_fills_db/`, `db/repositories/raw_fills_*`, `db/repositories/fills_*`, `db/repositories/market_data_*`
2. **Add platform_data contract files** for the Data Platform (`data_platform_contracts.py`) and for algorithm evaluation (`evaluation_contracts.py`).
3. **Introduce new adapters** in `platform_data/adapters.py`: `DataPlatformIngestionAdapter`, and extend `PlatformDataAccess` with a `.data_platform` entry.
4. **Build CostView evaluation layer.** Create `CostView/src/evaluation/` (model loading, orchestration) and `CostView/src/models/` (algorithm model definitions). These replace the direct data-access patterns that will be extracted.
5. **Redirect CostView internal imports.** Update `CostView/src/tca_query_service.py` and `CostView/src/attribution/` to consume data through Data Platform adapters rather than directly accessing storage.
6. **Deprecate legacy classes.** Mark `CostView/src/raw_fills_db.py`, `CostView/src/raw_bdib_db.py`, `CostView/src/fill_bdib_db.py`, and `CostView/src/processed_fills_db/` as fully deprecated once extraction completes.
7. Add more contracts and adapters only when a real caller needs them (YAGNI).
8. Defer any storage unification until there is a workload-driven reason.

---

## Non-goals

- No immediate rewrite into a single monorepo Python package layout.
- No immediate migration of SQLite analytical stores into PostgreSQL.
- The Data Platform extraction from CostView will be incremental; existing `CostView/src/` surfaces remain functional during the transition.

---

## Decision summary

The platform treats data as one logical domain with four owned subdomains:

| # | Subdomain | Owner | Role |
|---|-----------|-------|------|
| 1 | ExecutionView operational state | ExecutionView | Live order/route projections and audit |
| 2 | Data platform | Independent subsystem | Acquisition, processing, and storage of market/fill data |
| 3 | Algorithm evaluation and analytics | CostView | Model-driven evaluation and analytical reports |
| 4 | MarketView pre-trade context | MarketView | Reserved for future pre-trade market context |

Cross-subdomain access flows through `platform_data` adapters. The CostView
focus shifts from owning data infrastructure to owning algorithm evaluation
logic, with the new Data Platform subsystem providing clean, reliable data.
