# EMSX Logical Data Domain

> Boundary definition for shared platform data
> Last updated: 2026-06-03 (v3.3 — 修正适配器清单与实际代码对齐)
>
> **重要**: 本文档与实际代码的偏差见 [ADR-0013](adr/0013-platform-data-adapter-current-state.md)。

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

Cross-module adapter:

- `platform_data.adapters.HandoffExchangeAdapter` / `get_shared_handoff_exchange()` — ExecutionView ↔ CostView ↔ MarketView 交接
- ExecutionView 持久化走 `backend/api` 自身的 `RepositoryProvider`（`ENABLE_DB_PERSISTENCE` gate），不通过 platform_data`

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

- `DataPipeline/acquisition/` — BDIB market bar acquisition
- `DataPipeline/ingestion/` — fill and market data ingestion
- `DataPipeline/processing/` — cleaning, enrichment, aggregation, metrics
- `DataPipeline/storage/` — connection management, repositories, legacy DB facades
- `DataPipeline/orchestration/` — pipeline and migration management
- `DataPipeline/common/` — shared configuration (ProcessingConfig, schema, exchange_tz, mapping)

Legacy surfaces (all migrated — original files deleted from `CostView/src/`):

- ✅ `fill_fetch.py` → `DataPipeline/ingestion/fill_fetch.py` (SQLAlchemy replaced with ConnectionManager)
- ✅ `fill_ingestion.py` → `DataPipeline/ingestion/fill_ingestion.py`
- ✅ `fill_cleaner.py` → `DataPipeline/processing/fill_cleaner.py`
- ✅ `fill_processor.py` → `DataPipeline/processing/fill_processor.py`
- ✅ `fill_aggregator.py` → `DataPipeline/processing/fill_aggregator.py`
- ✅ `fill_bdib_integrated.py` → `DataPipeline/processing/fill_bdib_integrated.py`
- ✅ `bdib_fetcher.py` → `DataPipeline/acquisition/bdib_fetcher.py`
- ✅ `daily_metrics_calculator.py` → `DataPipeline/processing/daily_metrics_calculator.py`
- ✅ `pipeline.py` → `DataPipeline/orchestration/pipeline.py`
- ✅ `raw_fills_db.py` → `DataPipeline/storage/raw_fills_db.py`
- ✅ `raw_bdib_db.py` → `DataPipeline/storage/raw_bdib_db.py`
- ✅ `fill_bdib_db.py` → `DataPipeline/storage/fill_bdib_db.py`
- ✅ `processed_raw_bdib_db.py` → `DataPipeline/storage/processed_raw_bdib_db.py`
- ✅ `processed_fills_db/` → `DataPipeline/storage/processed_fills_db/`
- ✅ `CostView/src/db/connection.py` → `DataPipeline/storage/connection.py`
- ✅ `CostView/src/db/repositories/` → `DataPipeline/storage/repositories/`
- ✅ `CostView/src/db/schema/` → `DataPipeline/storage/schema/`
- ✅ `CostView/src/db/protocols.py` → `DataPipeline/storage/protocols.py`
- ✅ `CostView/src/db/dto.py` → `DataPipeline/storage/dto.py`
- ✅ `processing_config.py` → `DataPipeline/common/processing_config.py`
- ✅ `exchange_tz.py` → `DataPipeline/common/exchange_tz.py`
- ✅ `mapping.py` → `DataPipeline/common/mapping.py`
- ✅ `outdated_tickers.py` → `DataPipeline/common/outdated_tickers.py`
- ✅ `schema.py` → `DataPipeline/common/schema.py`
- ✅ `emsx_client.py` → `DataPipeline/acquisition/emsx_client.py`
- ✅ `order_label.py` → `DataPipeline/processing/order_label.py`
- ✅ `validate_raw_fills.py` → `DataPipeline/processing/validate_raw_fills.py`
- 🗑️ `tca_query_service.py.bak` — deleted (leftover backup file)

Cross-module entry:

- 管道摄取/状态经 `platform_data.pipeline_jobs`（`trigger_pipeline`, `get_job`）与 `platform_data.config_bridge`（`register_config_impl` / `get_config`）暴露
- `DataPlatformIngestionAdapter` 与 `build_platform_data_access()` 尚未实现（规划中，见 [ADR-0013](adr/0013-platform-data-adapter-current-state.md)）

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

Primary code surfaces (actual, 2026-08):

- `CostView/src/tca_query_service.py` — TCA and scorecard query（读取 `tca_route_summary` 汇总表）
- `CostView/src/tca_query_builder.py` — TCA 查询构建器
- `CostView/src/tca_cache.py` / `tca_fallback.py` / `tca_utils.py` — 查询缓存 / 降级 / 工具
- `CostView/src/monitoring/` — BDIB 健康度、指标覆盖率、报告聚合（`bdib_health.py`, `metric_coverage.py`, `report_aggregator.py`, `time_range.py`）
- `CostView/src/query_cli.py` / `secure_config.py` — CLI / 加密配置
- `backend/api/routers/costview.py` — API surface

> 注：`evaluation/`、`models/`、`attribution/`、`regime/`、`db/repositories/regime.py`、`execution_history_service.py` 为历史规划路径，当前不存在；执行历史读取经 `platform_data.execution_history_service` 提供。

Cross-module adapters (actual):

- `platform_data.adapters.get_tca_query_service()` — TCA / scorecard 查询工厂
- `platform_data.adapters.register_tca_service_impl()` — TCA 实现注入
- `platform_data.adapters.MarketReferenceDataAdapter` — 市场快照（BDIB / 日内特征）
- `platform_data.execution_history_service` — 执行历史读取路径
- `build_platform_data_access()` / `PlatformDataAccess` 未实现（规划中，见 [ADR-0013](adr/0013-platform-data-adapter-current-state.md)）

### 4. MarketView — pre-trade market context (placeholder)

> Reserved for future MarketView pre-trade market context data.
> Market reference data (BDIB, daily summary) is owned by the Data Platform
> subdomain and consumed by MarketView through adapters.

---

## Contract layer

Cross-module data contracts are defined in `platform_data/contracts/`. This is the **only legal source** for data types and constants that cross module boundaries (ExecutionView ↔ CostView ↔ MarketView).

Current contracts:

- `platform_data/contracts/fill_contracts.py` — `SCORECARD_COHORTS` tuple
- `platform_data/contracts/market_data_contracts.py` — (placeholder for future market data types)
- `platform_data/contracts/regime_contracts.py` — (placeholder for future regime types)
- `platform_data/contracts/data_platform_contracts.py` — `IngestionConfig`, `PipelineState`, `IngestionResult`
- `platform_data/contracts/evaluation_contracts.py` — (planned — algorithm model metadata, evaluation specs, output format)

Rule: Consumers import from `platform_data.contracts`, not from `CostView.src.*` directly.

---

## Adapter entry

> **v3.3 更新 (2026-06-03)**：实际代码与 v3.2 描述存在显著偏差。详见 [ADR-0013](adr/0013-platform-data-adapter-current-state.md)。
>
> 实际入口（按符号直接 import，无统一 PlatformDataAccess）：

The shared code entry is:

- `platform_data/__init__.py`
- `platform_data/adapters/` （子包，`__init__.py` 做向后兼容 re-export）
  - `handoff.py` — `HandoffExchangeAdapter` + `get_shared_handoff_exchange()`
  - `market.py` — `MarketReferenceDataAdapter`
  - `redis_handoff.py` — `RedisHandoffExchangeAdapter`
  - `tca_bridge.py` — `get_tca_query_service()`, `register_tca_service_impl()`
- `platform_data/contracts/`
- `platform_data/repositories.py`

#### 实际存在的适配器（2026-06-03）

| 适配器 / 函数 | 角色 | 所有者 | 消费方 |
|---|---|---|---|
| `HandoffExchangeAdapter` | 跨模块 handoff 交换（in-memory） | platform_data | 全部模块 |
| `RedisHandoffExchangeAdapter` | 跨模块 handoff 交换（Redis 微服务模式） | platform_data | 全部模块 |
| `get_shared_handoff_exchange()` | handoff 单例工厂（按 `EMSXVIEW_HANDOFF_BACKEND` 选后端） | platform_data | 全部模块 |
| `MarketReferenceDataAdapter` | 市场快照与日内特征 | Data Platform | MarketView / CostView |
| `get_tca_query_service()` | TCA 查询服务工厂 | platform_data | 业务模块 |
| `register_tca_service_impl(impl)` | TCA 实现注入 | platform_data | CostView / 启动钩子 |

#### 待实现（v3.2 描述但代码尚未提供）

- `ExecutionOperationalDataAdapter` — live execution state (owner: ExecutionView)
- `CostViewAnalyticsAdapter` — TCA and scorecard reports (owner: CostView) — 当前通过 `get_tca_query_service()` 间接获得
- `CostViewDatabaseAdapter` — read-only database queries via `DatabaseFacade` (owner: CostView)
- `ExecutionHistoryAdapter` — fill/order/route history (owner: Data Platform, consumed by CostView) — 契约类型已存在 `platform_data.contracts.execution_contracts`
- `DataPlatformIngestionAdapter` — ingestion trigger and pipeline status
- `PlatformDataAccess` — unified entry point holding all adapters
- `AlgorithmEvaluationAdapter` — model-driven evaluation output

新增适配器需走 [module-onboarding.md §B](module-onboarding.md) 流程。

#### 使用示例

```python
# 当前实际用法
from platform_data import (
    HandoffExchangeAdapter,
    get_shared_handoff_exchange,
    get_tca_query_service,
)
from platform_data.contracts.execution_contracts import ExecutionHistoryFillRow

# 取得 handoff 适配器
handoff = get_shared_handoff_exchange()
recommendations = handoff.list_cost_to_execution(limit=20)

# 取得 TCA 服务
tca = get_tca_query_service()
report = tca.build_tca_report(filters)
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
   - Acquisition: `bdib_fetcher.py` → `DataPipeline/acquisition/`
   - Ingestion: `fill_fetch.py`, `fill_ingestion.py` → `DataPipeline/ingestion/`
   - Processing: `fill_cleaner.py`, `fill_processor.py`, `fill_aggregator.py`, `fill_bdib_integrated.py`, `daily_metrics_calculator.py` → `DataPipeline/processing/`
   - Storage: `connection.py`, `repositories/`, `schema/`, `protocols.py`, `dto.py`, `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`, `processed_fills_db/` → `DataPipeline/storage/`
   - Orchestration: `pipeline.py` → `DataPipeline/orchestration/`
   - Common: `processing_config.py`, `exchange_tz.py`, `mapping.py`, `outdated_tickers.py`, `schema.py` → `DataPipeline/common/`
2. ✅ **Added platform_data contract files:** `data_platform_contracts.py` (IngestionConfig, PipelineState, IngestionResult, PipelineStatus). `evaluation_contracts.py` deferred (YAGNI).
3. ✅ **Introduced new adapters:** `DataPlatformIngestionAdapter` in `platform_data/adapters.py`, integrated into `PlatformDataAccess.data_platform`.
4. ⬜ **Build CostView evaluation layer** — deferred (out of scope for this extraction).
5. ✅ **Redirect internal imports.** All DataPipeline modules import from within DataPipeline. `CostView/src/db/` is a thin re-export layer.
6. ✅ **Deleted legacy classes.** `raw_fills_db.py`, `raw_bdib_db.py`, `fill_bdib_db.py`, `processed_raw_bdib_db.py`, `processed_fills_db/` removed from `CostView/src/`. Copied to `DataPipeline/storage/`.

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
