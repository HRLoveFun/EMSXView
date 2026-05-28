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

- `backend/api/db.py`
- `backend/api/service_provider.py`
- `backend/api/repositories/`
- `backend/api/models/`

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

Primary code surfaces (current):

- `DataPipeline/src/acquisition/` — BDIB market bar acquisition
- `DataPipeline/src/ingestion/` — fill and market data ingestion
- `DataPipeline/src/processing/` — cleaning, enrichment, aggregation, metrics
- `DataPipeline/src/storage/` — connection management, repositories, legacy DB facades
- `DataPipeline/src/orchestration/` — pipeline and migration management
- `DataPipeline/src/common/` — shared configuration (ProcessingConfig, schema, exchange_tz, mapping)

Legacy surfaces (all migrated — original files deleted from `CostView/src/`):

- ✅ `fill_fetch.py` → `DataPipeline/src/ingestion/fill_fetch.py` (SQLAlchemy replaced with ConnectionManager)
- ✅ `fill_ingestion.py` → `DataPipeline/src/ingestion/fill_ingestion.py`
- ✅ `fill_cleaner.py` → `DataPipeline/src/processing/fill_cleaner.py`
- ✅ `fill_processor.py` → `DataPipeline/src/processing/fill_processor.py`
- ✅ `fill_aggregator.py` → `DataPipeline/src/processing/fill_aggregator.py`
- ✅ `fill_bdib_integrated.py` → `DataPipeline/src/processing/fill_bdib_integrated.py`
- ✅ `bdib_fetcher.py` → `DataPipeline/src/acquisition/bdib_fetcher.py`
- ✅ `daily_metrics_calculator.py` → `DataPipeline/src/processing/daily_metrics_calculator.py`
- ✅ `pipeline.py` → `DataPipeline/src/orchestration/pipeline.py`
- ✅ `raw_fills_db.py` → `DataPipeline/src/storage/raw_fills_db.py`
- ✅ `raw_bdib_db.py` → `DataPipeline/src/storage/raw_bdib_db.py`
- ✅ `fill_bdib_db.py` → `DataPipeline/src/storage/fill_bdib_db.py`
- ✅ `processed_raw_bdib_db.py` → `DataPipeline/src/storage/processed_raw_bdib_db.py`
- ✅ `processed_fills_db/` → `DataPipeline/src/storage/processed_fills_db/`
- ✅ `CostView/src/db/connection.py` → `DataPipeline/src/storage/connection.py`
- ✅ `CostView/src/db/repositories/` → `DataPipeline/src/storage/repositories/`
- ✅ `CostView/src/db/schema/` → `DataPipeline/src/storage/schema/`
- ✅ `CostView/src/db/protocols.py` → `DataPipeline/src/storage/protocols.py`
- ✅ `CostView/src/db/dto.py` → `DataPipeline/src/storage/dto.py`
- ✅ `processing_config.py` → `DataPipeline/src/common/processing_config.py`
- ✅ `exchange_tz.py` → `DataPipeline/src/common/exchange_tz.py`
- ✅ `mapping.py` → `DataPipeline/src/common/mapping.py`
- ✅ `outdated_tickers.py` → `DataPipeline/src/common/outdated_tickers.py`
- ✅ `schema.py` → `DataPipeline/src/common/schema.py`
- ✅ `emsx_client.py` → `DataPipeline/src/acquisition/emsx_client.py`
- ✅ `order_label.py` → `DataPipeline/src/processing/order_label.py`
- ✅ `validate_raw_fills.py` → `DataPipeline/src/processing/validate_raw_fills.py`
- 🗑️ `tca_query_service.py.bak` — deleted (leftover backup file)

Canonical shared adapter:

- `platform_data.build_platform_data_access().data_platform` (implemented — `DataPlatformIngestionAdapter`)

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
- `backend/api/routers/costview.py` — API surface

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
- `platform_data/contracts/data_platform_contracts.py` — `IngestionConfig`, `PipelineState`, `IngestionResult`
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
- `CostViewDatabaseAdapter` \â€\” read-only database queries via `DatabaseFacade` (owner: CostView)
- `ExecutionHistoryAdapter` \â€\” fill/order/route history (owner: Data Platform, consumed by CostView)
- `HandoffExchangeAdapter` \â€\” cross-module handoff contracts (owner: platform_data)
- `PlatformDataAccess` \â€\” unified entry point holding all adapters

Planned adapters:

- `DataPlatformIngestionAdapter` \â€\” ingestion trigger and pipeline status (implemented — see `platform_data.adapters.DataPlatformIngestionAdapter`)
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

## Extraction status

### Completed (2026-05-07)

1. ✅ **Extract Data Platform subdomain.** Created `DataPipeline/` package and migrated all data surfaces from `CostView/src/`:
   - Acquisition: `bdib_fetcher.py` → `DataPipeline/src/acquisition/`
   - Ingestion: `fill_fetch.py`, `fill_ingestion.py` → `DataPipeline/src/ingestion/`
   - Processing: `fill_cleaner.py`, `fill_processor.py`, `fill_aggregator.py`, `fill_bdib_integrated.py`, `daily_metrics_calculator.py` → `DataPipeline/src/processing/`
   - Storage: `connection.py`, `repositories/`, `schema/`, `protocols.py`, `dto.py`, `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`, `processed_fills_db/` → `DataPipeline/src/storage/`
   - Orchestration: `pipeline.py` → `DataPipeline/src/orchestration/`
   - Common: `processing_config.py`, `exchange_tz.py`, `mapping.py`, `outdated_tickers.py`, `schema.py` → `DataPipeline/src/common/`
2. ✅ **Added platform_data contract files:** `data_platform_contracts.py` (IngestionConfig, PipelineState, IngestionResult, PipelineStatus). `evaluation_contracts.py` deferred (YAGNI).
3. ✅ **Introduced new adapters:** `DataPlatformIngestionAdapter` in `platform_data/adapters.py`, integrated into `PlatformDataAccess.data_platform`.
4. ⬜ **Build CostView evaluation layer** — deferred (out of scope for this extraction).
5. ✅ **Redirect internal imports.** All DataPipeline modules import from within DataPipeline. `CostView/src/db/` is a thin re-export layer.
6. ✅ **Deleted legacy classes.** `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`, `processed_fills_db/` removed from `CostView/src/`. Copied to `DataPipeline/src/storage/`.

### Remaining work

- Build `CostView/src/evaluation/` and `CostView/src/models/` (algorithm evaluation layer).
- Add more contracts and adapters only when a real caller needs them (YAGNI).
- Defer any storage unification until there is a workload-driven reason.

---

## Non-goals

- No immediate rewrite into a single monorepo Python package layout.
- No immediate migration of SQLite analytical stores into PostgreSQL.
- The Data Platform has been extracted from CostView. Analysis modules (regime/attribution) and execution history service now live in DataPipeline and platform_data respectively.

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
