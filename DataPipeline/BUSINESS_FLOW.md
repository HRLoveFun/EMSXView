# DataPipeline 业务流程梳理

> 适用版本：`branch = 001-architecture-module-completion`  
> 整理范围：`c:\Users\hrchen\Documents\EMSXView\DataPipeline` 全部子包

---

## 1. 模块定位与对外契约

`DataPipeline` 是独立的数据基础设施子域，**唯一公开 API** 在 `DataPipeline/__init__.py` 中声明：

| 公开符号 | 角色 | 来源 |
| --- | --- | --- |
| `Config` | 全部路径、表名、时序/格式、护栏开关的单一事实源 | `DataPipeline/config.py` |
| `ConnectionManager` | 集中化 SQLite 连接生命周期、读写权限分层 | `DataPipeline/storage/connection.py` |
| `AccessTier` | `READ` / `WRITE` 访问层级枚举 | 同上 |
| `DatabaseFacade` | 仓库统一入口（`fills_read`/`fills_write`/`raw_fills_*`/`market_data_*`/`integrated_*`/`regime_*`） | `DataPipeline/storage/facade.py` |

> 外部消费者应只 import 上述四个符号，**禁止** 直接 `from DataPipeline.storage.schema.columns import ...`，否则会在 minor 版本升级时破坏。

CLI 入口：`python -m DataPipeline --once`，对应 `DataPipeline/__main__.py`，最终调用 `orchestration.core.run_full_pipeline(...)`。

---

## 2. 子包职责矩阵

| 子包 | 一句话职责 | 关键产出 |
| --- | --- | --- |
| `acquisition/` | 拉取 Bloomberg EMSX 原始数据 | `raw_fills.db` 行、`raw_bdib.db` 行、FX rates |
| `ingestion/` | 拉取 + 落地 + ingestion 日志 | `fill_fetch.py`、`fill_ingestion.py` |
| `processing/` | 清洗、增强、聚合、BDIB 整合、衍生指标 | `processed_fills.db`、`agg_fills_10s`、`fill_bdib.db` |
| `analysis/` | 市场状态分类、成交归因 | `regime.db`、`fill_attribution_metrics` |
| `storage/` | 仓库模式访问、迁移、Facade | 跨库读写、DDL 版本管理 |
| `validation/` | 护栏校验：Schema、契约、违规、结果 | `ValidationResult`、`GuardStageResult` |
| `circuit_breaker/` | 三态熔断、注册表、告警、重试 | `CircuitBreaker`、`RetryPolicy` |
| `monitoring/` | 运行级 JSONL 日志、RunID、概要 | `{run_id}.jsonl`、summary dict |
| `orchestration/` | 阶段基类、Stage 集合、Context、Guard 包装 | 整条管道编排入口 |
| `common/` | 时区/映射/outdated ticker 共用工具 | 跨子包复用函数 |
| `tests/` | 单元/集成/基线快照 | 基线 JSON、测试结果 |

---

## 3. 端到端业务流程（9 个活动 Stage + 1 个废弃 Stage）

入口：`orchestration/core.py::PipelineFactory.create_daily_e2e_pipeline(skip_ingest, skip_bdib)`。

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        run_full_pipeline() 入口                          │
│  DataPipeline/__main__.py  →  orchestration/core.py::run_full_pipeline   │
└──────────────────────────────┬───────────────────────────────────────────┘
                               ▼
        ┌──────────────────────────────────────────────────┐
        │ PipelineContext 初始化（连接/配置/目标日期）       │
        │  - ConnectionManager (懒加载)                     │
        │  - DatabaseFacade    (懒加载)                     │
        │  - errors[] / summary{} / is_successful           │
        └──────────────────────┬───────────────────────────┘
                               ▼
                  ┌────────────────────────┐
                  │  GuardPipeline.run()   │  ← 护栏层（可选注入）
                  │  - 生成 run_id          │
                  │  - 启动 run_logger      │
                  │  - 创建 breaker_registry│
                  └────────────┬───────────┘
                               ▼
                  ┌────────────────────────┐
                  │  S0 Pre-Flight 静态检查  │  ← PR-3: Schema drift 扫描
                  │  SchemaDriftGuard        │     (DDL vs 代码层写入)
                  │  - 解析 db_partition.sql │
                  │  - 解析 inline_ddl.py    │
                  │  - 解析 fill_ingestion.py│
                  │  - 4 类漂移检测          │
                  │  - 白名单降级 INFO       │
                  │  - ERROR 阻断 + critical│
                  │    告警                  │
                  └────────────┬───────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│ Stage 顺序执行（BaseStage.execute → GuardStage.execute）                │
│  每个 Stage 可被: ① 熔断检查  ② 输入预检  ③ 输出校验  ④ JSONL 日志    │
└──────────────────────────────────────────────────────────────────────────┘
```

| Stage | 类 (位置) | 关键输入 | 关键输出 | 主要表 |
| --- | --- | --- | --- | --- |
> ⚠️ 旧 **S1 Ingest Excel (Legacy)** 已废弃并从本表移除，详见 §3.2 废弃 API 清单。

| Stage | 类 (位置) | 关键输入 | 关键输出 | 主要表 |
| --- | --- | --- | --- | --- |
| **S1** Process Raw Fills | `ProcessRawFillsStage` (`stages_ingest.py`) | `raw_fills.db` 当日数据 | 22 列 processed + `equ_ticker`（v2 起空字段输出 NULL） | `processed_fills`、`route_registry`（含 4 个 `count_*` 列，v2 修复）、`route_history`（v2 起字段直接取自 processed）、`route_event_history`（`order_history` 为 `route_history` 的 VIEW 派生，PR-1 方案 A 过渡版） |
| **S2** Aggregate Fills (10s) | `AggregateFillsStage` (`stages_ingest.py`) | `processed_fills` 单日 | route×timestamp 10s 桶（VWAP） | `agg_fills_10s` |
| **S3** Generate Order Labels | `GenerateOrderLabelsStage` (`stages_ingest.py`) | `processed_fills` 单日 | 订单级标签 | `order_label`（`ticker_registry.db`） |
| **S4** Integrate BDIB | `IntegrateBDIBStage` (`stages_process.py`) | `agg_fills_10s` + Bloomberg BDIB 10s bars + FX | TCA 衍生指标 | `raw_bdib`、`fill_bdib` |
| **S5** Write Manifest | `WriteManifestStage` (`stages_process.py`) | ticker registry | `market_fetch_manifest.json` | （无） |
| **S6** Daily Metrics | `CalculateDailyMetricsStage` (`stages_process.py`) | `raw_bdib` + Bloomberg bdh | ADV(5d/20d)、年化波动率、daily_vwap | `bdib_daily_summary` |
| **S7** Regime Daily Features | `RegimeDailyFeaturesStage` (`stages_analysis.py`) | 指数/BDIB 聚合 → market_index | vol/liq/trend 日级分类 | `daily_vol_regime`、`daily_liquidity_regime`、`daily_trend_regime` |
| **S8** Regime Fill Tagger | `RegimeFillTaggerStage` (`stages_analysis.py`) | `processed_fills` × `daily_*_regime` | 每笔成交的市场状态标签 | `fill_regime_labels` |
| **S9** Attribution Metrics | `AttributionMetricsStage` (`stages_analysis.py`) | `processed_fills` + `raw_bdib` + `regime` 配置 | 每笔成交的 IS/VWAP/反转指标 | `fill_attribution_metrics` |

> 默认 `--once` 模式：skip_bdib=True（S4、S6 被跳过）。日常运行时只跑 **S1 → S2 → S3 → S5**。  
> 全量模式（首跑或 force）：按上表顺序执行 S1..S9。
>
> ⚠️ **旧 S1 Ingest Excel 已废弃**：数据已不再从 Excel 获取，详见下方"§3.2 废弃 API 清单"。默认管道不再注册 Excel 摄入 Stage。
>
> ⚠️ **S1 v2 修复（field assignment / timezone semantics）**：2026-06 完成 v2 重构，详细字段语义与 deprecated 状态见 **§3.3 S1 v2 字段修复摘要**。

### 3.1 Stage 内部实现概要

**S1 处理（Clean + Process）**  
`processing/fill_cleaner.clean_emsx_fills` 三步：DFD 过滤 → 时区转换（NY → local exchange tz）→ 字段标准化。`processing/fill_processor.process_fills` 五步：algo 分类 → ccy/equ_ticker 推导 → 10s 钟时间戳 → 收盘竞价识别 → 路由 mkt_timestamp。`process_raw_fills_for_date` 再做：写 `processed_fills`、写 `route_registry`、构建 `route_history` / `route_event_history` 并 `upsert_execution_history`（**PR-1**：不再单独生成 `order_history` 行——`order_history` 是 `route_history` 的 VIEW 派生）。

> 注：S1 阶段的输入 `raw_fills` 由 `acquisition/bloomberg_fill_fetcher.py` + `ingestion/fill_fetch.py::FillFetch` 直接落库（内存 hash 集合 + DB hash 双层去重、SHA-256 校验、`upsert_raw_api_data` + `add_fetch_log_record`，并落 `fill_fetch_history` 审计）。**旧"Excel 摄入"已废弃**，详见 §3.2。

**S2 聚合**  
`processing/fill_aggregator.generate_agg_fills_10s`：按 `(OrderId, RouteId, mkt_timestamp)` groupby → 唯一值列 / `sum(FillShares)` / VWAP。

**S3 Order Label**  
`processing/order_label.generate_order_label_incremental`：逐日处理（避免 OOM），累计标签集向后传递；写入 `ticker_registry.db` 中的 `order_label` 表。

**S4 BDIB 整合（TCA）**  
`acquisition/bdib_fetcher.fetch_bdib_for_fills`：并行拉 BDIB 10s bars；`processing/fill_bdib_integrated.integrate_fills_bdib_for_date`：在内存中 left-join BDIB + FX + 每日指标，并 `_compute_derived_metrics`（VWAP slippage、Arrival slippage、PX diff、9 个累积 TCA 列、累计 vol/价值、tracking error、info ratio、波动率）。结果写入 `fill_bdib.db`。

**S5 Manifest**  
`analysis/downstream_interface.write_manifest`：序列化当前激活的 equ/ccy ticker 列表到 `market_fetch_manifest.json`，供下游 MarketFetch 监听。

**S6 Daily Metrics**  
`processing/daily_metrics_calculator.CalculateDailyMetrics.run_for_date`：并行 chunk 拉 `PX_VOLUME` / `VOLATILITY_30D` / `PX_LAST`，与 raw BDIB 10s bars 计算 ADV(5d/20d)、日内 VWAP、年化波动率。增量跳过已写入 `bdib_daily_summary` 的日期。

**S7 Regime 分类**  
- `regime/market_index_loader.load_market_index`：拉取指数/参考数据  
- `regime/vol_regime.classify`：VIX 阈值（缺则降级为 realized_vol_zscore）  
- `regime/liquidity_regime.classify`：换手率 z-score（lookback 60d）  
- `regime/trend_regime.classify`：MA + RSI 组合  
- 所有调用包在 `run_journal` contextmanager 中，写入 `audit_pipeline_runs`。

**S8 Fill Tagging**  
`regime/fill_regime_tagger.tag_fills`：从 `processed_fills` 拉区间数据 → `derive_market_code`（EUR 折为 `EU`）→ 关联三种 regime → 检查 `ref_macro_event_calendar` 标记 macro window → 用 `assign_time_bucket`（仅 5 个启用市场）打 `time_bucket` → UPSERT 到 `fill_regime_labels`。

**S9 Attribution**  
`analysis/attribution/writer.run_metrics`：拉 1min bar panel → 计算 `arrival_px` / `interval_vwap` / `mid_at_fill` / `mid+N` → `slippage_bps`（IS / VWAP） + `reversal_bps`（1m/5m/30m） → `pct_adv`（与 `bdib_daily_summary.adv_20d` 关联）→ UPSERT `fill_attribution_metrics`。完成后写 `audit_pipeline_runs` + `audit_research_snapshots`（SHA-256 快照）。

---

## 3.2 废弃 API 清单（Deprecated — v2.0 移除）

> 业务约束：**数据已不再从 Excel 获取**。下表所列 API 仅作历史归档兼容保留，调用时均会发出 `DeprecationWarning`（Python 标准 `warnings` 模块）并在关键路径写 `logger.warning`。请迁移至 **Bloomberg API 摄入（`fill_fetch.py`）**。

| 符号 | 位置 | 状态 | 替代方案 |
| --- | --- | --- | --- |
| `IngestExcelStage`（**旧 S1** Ingest Excel） | `orchestration/stages_ingest.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch`（Bloomberg API） |
| `run_ingest()` | `orchestration/core.py` | ❌ 已废弃（v2.0 移除） | `run_full_pipeline(skip_ingest=True)` |
| `ingest_excel_file()` | `ingestion/fill_ingestion.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch.fetch_and_store()` |
| `ingest_all_excel_files()` | `ingestion/fill_ingestion.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch` 批量拉取 |

**废弃标记层级**：

1. **模块文档**：在 `fill_ingestion.py` 文件头标注 `Mode 1 (DEPRECATED — v2.0 移除)`。
2. **类/函数 docstring**：使用 Sphinx `.. deprecated::` 指令。
3. **运行时警告**：调用时发出 `DeprecationWarning`（`stacklevel=2`，定位到调用方）。
4. **关键路径日志**：`create_daily_e2e_pipeline(skip_ingest=False)` 注册**旧 S1** 前写 `logger.warning(...)`。
5. **管道默认值保护**：`PipelineFactory.create_daily_e2e_pipeline` 默认 `skip_ingest=True`，**旧 S1** 在日常运行中不执行。

**升级路径**：

- 任何调用 `run_ingest()` / `ingest_excel_file()` / `ingest_all_excel_files()` 的脚本需迁移到 `fill_fetch.py`。
- 不再有"全量模式（首跑或 force）"会执行**旧 S1**；`run_full_pipeline` 永远跳过 Excel 摄入。
- v2.0 将删除上述四个符号；届时调用将报 `AttributeError`，提醒升级。

---

## 3.3 S1 v2 字段修复摘要（field assignment / timezone semantics）

> 适用版本：`branch = 001-architecture-module-completion`（2026-06 S1 数据修复 v2）  
> 实施范围：`ingestion/fill_ingestion.py`、`processing/fill_processor.py`、`storage/repositories/fills.py`、`storage/schema/inline_ddl.py`  
> 验证报告：`docs/s1_replay_validation_20260416.md`  
> 下游兼容矩阵：`specs/002-pipeline-guardrail/s1-downstream-compat-matrix.md`

S1（`ProcessRawFillsStage` → `process_raw_fills_for_date`）在长期演进中累积了 4 类问题：缺失值/默认值策略不一致、列顺序与主键语义错位、关键字段空白未赋值、时区语义混用。v2 修复统一以下约定。

### 3.3.1 时区语义（必读）

S1 写入 4 张表的所有时间列统一归为 3 类，**严禁混用**：

| 类型 | 包含列 | 时区 | 字符串格式 | 样例 |
| --- | --- | --- | --- | --- |
| **原始 NY tz** | `DateTimeOfFill` / `NyOrderCreateAsOfDateTime` / `NyTranCreateAsOfDateTime` | `America/New_York` | ISO8601 **含 tz 后缀** | `2026-04-16T11:49:59-04:00` |
| **派生 local exchange tz** | `local_fill_datetime` / `mkt_timestamp` / `order_as_of_date` / `exchange_exec_time` / `route_as_of_time` / `first_fill_time` / `last_fill_time` / `event_timestamp` | `Config.EXCHANGE_TZ_MAP[Exchange]`（按订单所属交易所） | ISO8601 / `YYYYMMDD` / `HH:MM:SS` **无 tz 后缀** | `2026-04-16T23:49:59`、`20260416`、`09:49:59` |
| **UTC** | `source_refreshed_at` | `UTC` | ISO8601 **含 `+00:00` 后缀** | `2026-06-18T03:41:29+00:00` |

**实施细节**：

- `local_fill_datetime` 在 `processing/fill_cleaner.derive_exchange_times` 中由 `batch_convert_ny_to_local(parsed, exchange_col)` 生成（10-50× vectorized 性能）。
- `first_fill_time` / `last_fill_time` 在 `ingestion/fill_ingestion._first_last_event_time` 中**统一用 `local_fill_datetime`**（v2 修复前混用 `local_fill_datetime` + `DateTimeOfFill` 字符串比较，跨日/跨午时字典序与时间序不一致）。先 `pd.to_datetime(..., errors="coerce")` 解析为 datetime 对象，再 `min/max` 后用 `strftime("%Y-%m-%dT%H:%M:%S")` 输出。
- `source_refreshed_at` v2 改用 `datetime.now(timezone.utc).isoformat(timespec="seconds")`（v2 修复前用 `datetime.utcnow()` 输出 naive UTC，naive 字符串跨 tz 解析歧义）。
- `event_timestamp`（`route_event_history`）v2 修复前是 `local_fill_datetime or DateTimeOfFill` 兜底，与 `first_fill_time` 同问题；修复后统一为 `local_fill_datetime`。

### 3.3.2 `LimitPrice` / `StopPrice` 默认值策略

- **缺失/无效 → NULL（非 `"0"`）**。下游消费方（`CostView/src/tca_query_builder.py`）使用 `>0` 过滤 0 值；v2 修复后缺失即为 NULL，不会被错误地参与"等于 0"判断。
- **列类型 `TEXT` → `REAL`**：v2 修复后 `inline_ddl.init_raw_fills_schema` 将两列改为 `REAL`，与 `processed_fills.FillPrice` / `FillShares` 一致。SQLite 类型亲和下，写入数字字符串会被自动转换，历史遗留的 `"0"` 字符串由 S1 重跑时 `pd.to_numeric(errors="coerce")` 自然刷为 0（数字），下游逻辑保持兼容。
- `_parse_fill_messages` 内部使用 `getElementAsFloat` 抓取，异常/缺失 → `None`（v2 修复已确认未赋字符串 `"0"`）。

### 3.3.3 `processed_fills` 主键与 `key_columns` 对齐

- **DDL 主键**：`PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)`（`storage/schema/inline_ddl.init_processed_fills_schema` line 285）。
- **DDL 列顺序**：`FillId, OrderId, RouteId, mkt_timestamp, order_as_of_date, ...`（v2 修复**未**改列顺序；列顺序是 cosmetic 调整，列为 P2）。
- **`upsert_processed_fills` 的 `key_columns` v2 修复**：由 `["FillId"]` 改为 `["OrderId", "RouteId", "FillId", "order_as_of_date"]`，与 DDL 主键 4 元组对齐。当前 `_upsert_fixed_schema` 实际未用 `key_columns` 生成 `ON CONFLICT`（依赖 SQLite 唯一键判重），运行时行为不变；目的是与 schema 语义保持一致，避免未来 SQLite 升级时行为漂移。

### 3.3.4 `route_registry` count 列

- **DDL 包含 4 列**：`count_fill` / `count_broker` / `count_algo` / `count_trader`（`storage/schema/columns.ROUTE_REGISTRY_COLUMNS` + `COLUMN_TYPE_MAP` 标 INTEGER）。
- **v2 修复根因**：原 `upsert_route_registry(processed)` 时 DataFrame 没有这 4 列，`_upsert_fixed_schema` 按 `expected_columns` 过滤后**不写入** → DB 永远 NULL。
- **修复实现**：`process_raw_fills_for_date` 在 `upsert_route_registry` 之前对 `processed` 按 `(OrderId, RouteId)` groupby 计算 `count_fill = nunique(FillId)` / `count_broker = nunique(Broker)` / `count_algo = nunique(algo)` / `count_trader = nunique(TraderName)`，用 `merge` 写入 `processed_for_registry` 副本，再调 `upsert_route_registry(processed_for_registry)`。
- **验证结果（2026-04-16 replay）**：4 个 count 列写入率 **100%**（70187 行）。

### 3.3.5 `route_history` / `route_event_history` 字段来源

- **保留字段**：`equ_ticker` / `ccy_ticker` / `Side`（**必须保留**）。证据：`CostView/src/tca_query_builder.py:129, 146-148, 183-185, 195, 217` 与 `platform_data/execution_history_service.py:85-87, 147-148, 216-217` 全部 `LEFT JOIN route_registry` 或 `route_history` 取这 3 列做高频 JOIN key。`route_event_history` 同样保留以做调试追溯。
- **v2 修复根因**：原 `_build_execution_history_frames` 中 `route_attrs = route_reg_df[["OrderId", "RouteId", "equ_ticker", "ccy_ticker", "Side"]].drop_duplicates()` 后 `processed_df.merge(route_attrs, ...)`。`route_reg_df` 自身是 `processed` 的衍生（line 389），导致 `equ_ticker` 依赖 `processed.equ_ticker` → 二次中转 → 一旦 `processed.equ_ticker` 为空（`add_equity_ticker` 拼接出空字符串时）则 `route_history.equ_ticker` 全部继承空值。
- **修复实现**：移除 `route_attrs` 二次 merge，**所有字段（`equ_ticker` / `ccy_ticker` / `Side` / `Broker` / `algo` / `TraderName` / `Exchange`）直接从 `processed_df` 自身取**（`groupby` 取 `group.get(...)` 与 `itertuples` 取 `row._asdict()[...]`），与 `event_records` 同源。
- **验证结果（2026-04-16 replay）**：`route_history` 写入率 99.9% / 100% / 100%；`route_event_history` 100% / 100% / 100% / 100%（含 `source_refreshed_at`）。

### 3.3.6 `processed_fills.equ_ticker` 空字段处理

- `add_equity_ticker` 拼接规则：`(Ticker + " " + Exchange + " Equity").str.strip()`。
- **v2 修复根因**：当 `Ticker` 或 `Exchange` 为空/空白时，拼接出 `"Ticker  Equity"`（双空格）或 `" Equity"`，错误地保留为字符串而不是 None。
- **修复实现**：`add_equity_ticker` 内增加 `blank_mask = exchange_blank | ticker_blank`（覆盖 `isna()` / `str.strip()==""` / 字符串 `"nan"`/`"none"`），`df.loc[blank_mask, "equ_ticker"] = np.nan` 替换为 NULL。
- **单元测试**：`DataPipeline/tests/guardrail/test_add_equity_ticker.py` 7 个用例覆盖 `test_add_equity_ticker_empty_exchange` / `test_add_equity_ticker_empty_ticker` / `test_add_equity_ticker_eur_cache_miss` 等。`pytest -v tests/guardrail/test_add_equity_ticker.py` **7/7 通过**。

### 3.3.7 raw_fills 派生列 deprecated 状态

- **保留 4 个 deprecated 派生列**（`inline_ddl.init_raw_fills_schema`）：

  | 列 | 状态 | 说明 |
  | --- | --- | --- |
  | `order_as_of_date` | ✅ 保留（partition key） | S1 分区索引基础，按日期归档 |
  | `order_as_of_time` | ⚠️ deprecated | v2 起停止写入，v3.0 删除 |
  | `exchange_exec_time` | ⚠️ deprecated | v2 起停止写入，v3.0 删除 |
  | `route_as_of_time` | ⚠️ deprecated | v2 起停止写入，v3.0 删除 |
  | `local_fill_datetime` | ⚠️ deprecated（raw_fills 中） | v2 起停止写入（仅在 `processed_fills` 保留）；v3.0 删除 |
  | `ingested_at` | ⚠️ deprecated | 与 `fetched_at` 重复，v3.0 删除（保留至 2.x 向后兼容） |

- **同步点**：`CostView/tests/test_tca_query_service.py:198-208` fixture + `scripts/ops/import_excel_fills.py:818-845` legacy DDL 已同步列类型与 deprecated 注释。
- **核心语义**：`raw_fills` 是 BBG 原始落地区，**不做派生**。审计由 `source_date` / `fetched_at` + `ingestion_log` 表承担，不在数据列上混入派生字段。

### 3.3.8 验证矩阵（2026-04-16 S1 replay）

| 表 | 关键列 | 修复前 | 修复后（v2） |
| --- | --- | --- | --- |
| `raw_fills` | `LimitPrice` / `StopPrice` | TEXT + 可能 `"0"` 字符串 | REAL + NULL（非 `"0"`） |
| `processed_fills` | `equ_ticker` | 拼接出 `"Ticker  Equity"` | 99.3% 命中（空字段 → NULL） |
| `route_registry` | `count_fill` / `count_broker` / `count_algo` / `count_trader` | 0% 命中（NULL） | **100%** |
| `route_history` | `equ_ticker` / `ccy_ticker` / `Side` | 0% / 0% / 0%（继承 processed 空值） | 99.9% / 100% / 100% |
| `route_history` | `first_fill_time` / `last_fill_time` | 字符串字典序比较（错误） | ISO8601 + pd.to_datetime 解析后 min/max |
| `route_event_history` | `equ_ticker` / `ccy_ticker` / `Side` | 0% / 0% / 0% | 100% / 100% / 100% |
| `route_event_history` | `source_refreshed_at` | `2026-06-18T03:41:29`（naive UTC） | `2026-06-18T03:41:29+00:00`（带 tz 后缀） |
| `route_event_history` | `event_timestamp` | `local_fill_datetime or DateTimeOfFill`（混用） | 统一 `local_fill_datetime` |

> 重跑命令：`python -m DataPipeline --date 20260416`（需 Bloomberg API 在线）；  
> 验证脚本：`docs/s1_replay_validation_20260416.md` 附录。

---

## 4. 护栏（GuardPipeline）子系统

> 目标：在不侵入现有 `FinancialPipeline` 的前提下注入校验/熔断/日志。

```
┌────────────────┐    wrap     ┌──────────────────┐
│ FinancialPipe  │ ──────────▶ │  GuardPipeline   │
│  (stages S1..S9)             │  run(context)    │
└────────────────┘             └─────────┬────────┘
                                          │ for each stage
                                          ▼
                          ┌──────────────────────────────┐
                          │ 1. 跳过？(skip config)         │
                          │ 2. 熔断器 OPEN? → 阻断后续       │
                          │ 3. GuardStage.execute()         │
                          │    - before_stage()             │
                          │    - stage.execute()            │
                          │    - Validator.validate_output()│
                          │    - record_success/failure     │
                          │ 4. 写 STAGE_START/END/VIO/CB   │
                          └──────────────────────────────┘
```

### 4.1 三大护栏组件

| 组件 | 位置 | 关键能力 |
| --- | --- | --- |
| `Validator` | `validation/validator.py` | Pydantic `model_validate` 逐条校验；按 `ValidationPolicy`（STRICT/RELAXED）分流；映射 Pydantic 错误到 `ViolationType` 和 `SeverityLevel`；空数据集策略 `GUARDRAIL_EMPTY_DATASET_POLICY` |
| `CircuitBreaker` | `circuit_breaker/breaker.py` | CLOSED→OPEN→HALF_OPEN 三态；按 `run_id`+`stage` 隔离；严重等级化触发（CRITICAL 立即 OPEN，ERROR 累计阈值，INFO 仅记录） |
| `CircuitBreakerRegistry` | `circuit_breaker/breaker_registry.py` | `get_or_create(run_id, stage)`；`cleanup(run_id)` 释放；`any_open(run_id)` 状态聚合 |
| `SchemaRegistry` | `validation/schema_registry.py` | 注册每个 Stage 的 INPUT/OUTPUT Pydantic 模型 + 策略；`check_contract(up, down)` 静态契约检查 |
| `ContractChecker` | `validation/contract_checker.py` | 字段存在性 / 类型兼容性 / 必填约束三检，输出 `COMPATIBLE` / `WITH_WARNING` / `INCOMPATIBLE` |
| `SchemaDriftGuard` | `pipeline_guards/schema_drift_guard.py` | **PR-3**：扫描 DDL 与代码层写入路径的 schema 漂移；4 类检测（PRIMARY_KEY_TYPE_MISMATCH / COLUMN_MISSING_IN_DDL / COLUMN_MISSING_IN_CODE / VALUE_TYPE_MISMATCH）；白名单降级 INFO，未知漂移 ERROR 阻断 + critical 告警；仅检查不自动修复 |
| `RetryPolicy` | `circuit_breaker/retry_policy.py` | 指数退避（`max_retries`、`base_delay`、`backoff_factor`） |
| `PipelineRunLogger` | `monitoring/run_logger.py` | 内存缓冲，flush 到 `{GUARDRAIL_LOG_DIR}/{run_id}.jsonl`，包含 RUN_START/STAGE_START/STAGE_END/VIOLATION/EXCEPTION/CIRCUIT_BREAK/RUN_END |
| `StageLogger` | `monitoring/stage_logger.py` | 阶段级条目构造器 |
| `Alert` | `circuit_breaker/alert.py` | 结构化日志告警 + 邮件/Webhook 扩展点 |
| `generate_run_id` | `monitoring/run_id.py` | `YYYYMMDD-HHMMSS-xxxxxx` 格式 |
| `generate_summary` | `monitoring/summary.py` | 统计 completed / failed / skipped / circuit_broken / total_violations |

### 4.2 校验策略矩阵

| 阶段 | 模式 | 策略 | 失败时 |
| --- | --- | --- | --- |
| Fetcher（外部 Bloomberg 拉取） | External | RELAXED（仅类型） | 告警但放行 |
| S1–S9 | Internal | STRICT | ERROR 累加达阈值触发熔断；CRITICAL 立即熔断 |

### 4.3 熔断规则

- **触发**：连续 `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD`（默认 3）次 ERROR **或** 任意 CRITICAL 异常。
- **行为**：阶段直接返回 `StageStatus.CIRCUIT_BROKEN`，后续阶段不再执行（`GuardPipeline.run` 中 `break`），整管道状态置为 `RunStatus.CIRCUIT_BROKEN`，发送 `level=critical` 告警。
- **恢复**：手动 `breaker.reset()` → HALF_OPEN；下一次探测成功 → CLOSED；HALF_OPEN 期间任何非 INFO 失败立即回退 OPEN。
- **隔离**：`run_id` 维度隔离，不同运行互不影响；运行结束后 `cleanup(run_id)` 释放内存。

### 4.4 降级开关

- `GUARDRAIL_ENABLED=false` → 完全关闭护栏（`BaseStage.execute` 仍跑，但无校验/熔断/JSONL）。
- `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR=true` → 校验失败仅日志，**不**计入熔断计数。
- `GUARDRAIL_EMPTY_DATASET_POLICY=accept` → 空数据集通过；`=reject`（默认）生成 1 条 ERROR 违规。

---

## 5. 存储层

### 5.1 9 个 SQLite 数据库

`ConnectionManager` 注册的数据库（按 S1 → S9 流转顺序）：

| DB 名 | 路径 (默认) | 关键表 | 写入方 | 读取方 |
| --- | --- | --- | --- | --- |
| `raw_fills` | `raw_fills.db` | `raw_fills`、`fetch_log`、`order_fetch_log`、`ingestion_log` | Fetcher | S1 |
| `processed_fills` | `processed_fills.db` | `processed_fills`、`route_registry`、`agg_fills_10s`、`agg_processed_fills`、`processed_fills_1min`、`order_label`（B4 迁移后） | S1/S2/S3 | S4/S6/S7 |
| `raw_bdib` | `raw_bdib.db` | `raw_bdib`、`bdib_daily_summary` | S4、S6 | S4、S6、S9 |
| `processed_raw_bdib` | `processed_raw_bdib.db` | `processed_raw_bdib` | （A8 后已退役，env `PROCESSED_RAW_BDIB_ENABLED=1` 重新启用） | — |
| `fill_bdib` | `fill_bdib.db` | `fill_bdib` | S4 | CostView |
| `regime` | `regime.db` | `daily_vol_regime`、`daily_liquidity_regime`、`daily_trend_regime`、`fill_regime_labels`、`fill_attribution_metrics`、`audit_regime_config_versions`、`audit_pipeline_runs`、`audit_research_snapshots`、`ref_*` | S7/S8/S9 | S8/S9/CostView |
| `fill_fetch_history` | `fill_fetch_history.db` | `fill_fetch_history` | Fetcher | 审计 |
| `execution_history` | `execution_history.db` | `route_registry`、`route_history`、`route_event_history`（**PR-1**：`order_history` 是 `route_history` 的 VIEW 派生，无独立物理表） | S1（写 `route_history` / `route_event_history`） | CostView |
| `ticker_registry` | `ticker_registry.db` | `equ_ticker_registry`、`ccy_ticker_registry`、`order_label`、`eur_composite_ticker_cache` | S1/S3 | S4/S5/S6 |

> 数据根目录由 `EMSXVIEW_DATA_DIR` 环境变量覆盖；默认 `CostView/data`（向后兼容）。

### 5.2 连接管理关键约定

- `AccessTier.READ`：禁止 INSERT/UPDATE/DELETE；同一线程内通过 `threading.local` 缓存连接（避免每次 ~50µs 重建开销）。
- `AccessTier.WRITE`：每次新建连接；自动应用 `journal_mode=WAL` + `foreign_keys=ON` + `busy_timeout=30s`。
- 全部连接由 `AccessControlledConnection` 包装，在 `execute()` 时按 SQL 正则分类做权限校验。
- 迁移统一走 `DataPipeline/storage/schema/migrations/apply.py`：读取 `PRAGMA user_version`，按 `vN_to_vN+1.sql` 顺序应用。`SCHEMA_VERSION=3` 为当前目标。

### 5.3 仓库分层

- `storage/connection.py` → 连接访问控制
- `storage/facade.py` → 9 个仓库聚合入口
- `storage/repositories/*.py` → 8 个表领域（fills、raw_fills、market_data、integrated、regime、fetch_history 等）
- `storage/schema/columns.py` → EMSX 列定义 + RAW_BDIB 列定义
- `storage/schema/migrations/` → forward-only DDL 链

---

## 6. 横切关注点（Cross-Cutting）

| 关注点 | 实现位置 | 说明 |
| --- | --- | --- |
| **时区** | `common/exchange_tz.py` | `NY_TZ` + `batch_convert_ny_to_local`，按 Exchange 分组 vectorized 转换（10-50× 单行调用）。**v2 修复后**：所有 S1 派生时间列统一为 local exchange tz（无 tz 后缀），`source_refreshed_at` 统一为 UTC（含 `+00:00` 后缀）。详见 **§3.3.1 时区语义**。 |
| **Algo 分类** | `common/mapping.py` | VWAP / TWAP / POV / Close / 收盘竞价时间映射 |
| **Outdated Ticker** | `common/outdated_tickers.py` | 基于 `outdated_tickers.json` 持久化墓碑；BDIB 拉取与 Manifest 生成时跳过；`Cannot find exchange info` 时自动登记 |
| **过期股票处理** | `processing/fill_processor._fetch_composite_tickers` | EUR 复合代码 `cache-first`（`eur_composite_ticker_cache` 表）+ xbbg `blp.bdp` chunked + 单 chunk 独立线程超时 |
| **进度报告** | 各 Stage 内 `print(f"[STAGE] {marker_name} {pct} ...", flush=True)` | 防止前端因长任务无输出误判 stalled |
| **去重** | `FillFetch._preload_known_hashes` + `compute_data_hash` | 内存 hash set + DB hash 双层 |
| **FX 转换** | `acquisition/fx_fetcher.py` | `USD{ccy} Curncy` 取 PX_LAST 并取倒数，失败/空时降级为 1.0 |
| **交易日期防护** | `bdib_fetcher._is_safe_bdib_query_date` | 拒未来日 + 周末/节假日 + 距当前不足 BDIB_LATEST_READY_HOUR_LOCAL |
| **KRW 补零** | `processing/fill_processor.add_equity_ticker` | KRW 股票 Ticker 自动 zfill(6) |
| **荷兰 NA 修复** | `processing/fill_cleaner.normalize_fill_columns` | pandas 把字符串 `"NA"` 解析为 NaN，显式还原为 `"NA"` |
| **归档加密** | `storage/crypto.py` | raw_fills 加密列（与 `access_impl.py` 配合） |
| **备份/归档** | `storage/backup.py` / `storage/archiver.py` | 时间戳 `.bak` 文件 / 长期冷存 |
| **审计** | `audit_pipeline_runs`、`audit_research_snapshots` | 每次 stage 运行 SHA-256 快照，便于复现 |

---

## 7. 一条记录的完整生命周期（单笔 Fill）

```
Bloomberg EMSX (T+0)
  │  ① GetFills via blpapi  →  raw_fills.db（Fetcher 直接落库）
  ▼
raw_fills  ────────────────────────────────────────────────┐
  │  source_date, EMSX 列(28)                                  │
  ▼                                                            │
processing.fill_cleaner  +  processing.fill_processor          │
  │  ② 过滤 DFD → 时区转换 → 字段标准化                        │
  │  ③ algo/ccy_ticker/equ_ticker/mkt_timestamp 等派生          │
  ▼                                                            │
processed_fills (S1) ─── 同事务写入 ───┐                         │
  │  27+5 列                              │  execution_history  │
  │                                       │  (route/event；order │
  │                                       │   为 route 的 VIEW)  │
  ▼                                       ▼                     │
agg_fills_10s (S2)                    execution_history.db      │
  │  groupby(OrderId, RouteId, mkt_ts)                           │
  │  VWAP + FillShares sum                                       │
  ▼                                                             │
order_label (S3) ── ticker_registry.db ─┐                       │
  │  订单级标签 (side/amount/algo)     │  BDIB                  │
  │                                     ▼                       │
  │  (BDIB 10s bars via xbbg)        raw_bdib (S4 拉取阶段)     │
  │  + FX rates                         │  compute_derived_fields│
  │                                     │  (vwap, log_chg_pct)   │
  │                                     ▼                       │
  │                                  raw_bdib + 内存衍生        │
  │                                     │                       │
  │                                     ▼                       │
  │                            fill_bdib (S4 集成阶段)           │
  │                              LEFT JOIN agg_fills_10s          │
  │                              + FX + 日级指标                 │
  │                              + 9 个累积 TCA 列              │
  │                                                             │
  │  bdib_daily_summary (S6) ─────────── PX_VOLUME /             │
  │                                     VOLATILITY_30D /         │
  │                                     PX_LAST + 日内 VWAP      │
  │                                                             │
  │  daily_market_index (S7) ─── 指数/参考数据                  │
  │     │                                                        │
  │     ▼                                                        │
  │  daily_vol_regime     daily_liquidity_regime     daily_trend_regime
  │                                                             │
  │  fill_regime_labels (S8) ── 三种 regime × macro × time_bucket
  │                                                             │
  │  raw_bdib 1min panels (S9) ── arrival_px / interval_vwap   │
  │     │                            / mid_at_fill / mid+N       │
  │     ▼                                                        │
  │  fill_attribution_metrics (S9) ── IS / VWAP / reversal bps  │
  │                                    + pct_adv + participation │
  │                                                             │
  └───────────────►  CostView / MarketView 业务消费 ◄─────────────┘
```

---

## 8. 配置与功能开关（`Config`）

| 类别 | 关键开关 | 默认值 | 说明 |
| --- | --- | --- | --- |
| 数据根 | `DATA_DIR` | `CostView/data` | 通过 `EMSXVIEW_DATA_DIR` 覆盖 |
| 拉取范围 | `FIRST_RUN_LOOKBACK_DAYS` | 60 | 首跑回溯天数 |
| BDIB | `BDIB_EXCHANGE` | 24 个交易所 | 拉取白名单 |
| BDIB | `BDIB_LATEST_READY_HOUR_LOCAL` | 8 | 当日 BDIB 安全就绪小时 |
| BDIB | `BDIB_PARQUET_ENABLED` | false | Parquet 双写 (Phase A) |
| BDIB | `BDIB_PARQUET_DIR` | `data/market/bdib_10s` | Parquet 目录 |
| BDIB | `BDIB_QUERY_ENGINE` | `sqlite` | `sqlite` / `parquet` |
| 分区 | `PARTITION_DUAL_WRITE` | false | 分区双写 (Phase B) |
| 分区 | `PARTITION_READ_NEW` | false | 读新分区 |
| 护栏 | `GUARDRAIL_ENABLED` | true | 护栏总开关 |
| 护栏 | `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD` | 3 | 熔断阈值 |
| 护栏 | `GUARDRAIL_RETRY_MAX` | 3 | Fetcher（外部 Bloomberg 拉取）重试次数 |
| 护栏 | `GUARDRAIL_VALIDATION_STRICT_MODE` | true | 全局严格模式 |
| 护栏 | `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR` | false | 校验降级放行 |
| 护栏 | `GUARDRAIL_EMPTY_DATASET_POLICY` | `reject` | 空数据集策略 |
| 护栏 | `GUARDRAIL_LOG_DIR` | `logs/pipeline/guardrail` | JSONL 日志目录 |
| 护栏 | `GUARDRAIL_BASELINE_DIR` | `DataPipeline/tests/baselines` | 基线快照目录 |
| 并发 | `MAX_PARALLEL_DATES` | 1 | 单次并行日期数（避免 OOM） |
| 并发 | `MAX_PARALLEL_TICKERS` | 1 | 单次并行 ticker 数 |
| 兼容 | `PROCESSED_RAW_BDIB_ENABLED` | false | 重新启用 `processed_raw_bdib` |
| BBG | `BBG_COMPOSITE_QUERY_TIMEOUT_SEC` | 45 | EUR 复合 ticker 查询单 chunk 超时 |

> **历史策略数据**：`EXECUTION_HISTORY_SOURCE_POLICY` / `EXECUTION_HISTORY_REFRESH_POLICY` 描述了 fills/orders/routes/route_events 四类表的来源优先级与刷新策略。

---

## 9. 错误处理与可观测性

| 现象 | 触发 | 处理 |
| --- | --- | --- |
| Bloomberg 超时（3 次连续 TIMEOUT 事件） | `BloombergFillFetcher` | 自动 disconnect → 2s sleep → reconnect；上层 `max_retries` 重试 |
| BBG `blp.bdp` 单 chunk 挂起 | `_fetch_one_bbg_chunk` | 独立 `ThreadPoolExecutor(max_workers=1)` + `future.result(timeout)`，超时即跳过 |
| BDIB `Cannot find exchange info` | `bdib_fetcher._is_outdated_ticker_error` | 写入 `outdated_tickers.json` 墓碑，后续拉取跳过 |
| EUR 复合代码缓存未命中 | `add_equity_ticker` | BBG 查询并回写 `eur_composite_ticker_cache` |
| Stage 业务异常 | `BaseStage.execute` | 顶层 try/except → `context.log_error` → 返回 False，管道中断 |
| Stage 校验失败 | `Validator.validate_output` | 按 SeverityLevel 处理：INFO 仅记、ERROR 累计、CRITICAL 立即熔断 |
| 熔断触发 | `CircuitBreaker.record_failure` | `_transition_to_open` + `alert_callback` 写结构化告警 |
| 内存峰值 | 各 Stage 循环体内 `del` + `gc.collect()` | 防止数百 ticker × 数月 BDIB 全部加载到内存 |
| 进度停滞（前端 stalled 误判） | 长 Stage（如 BDIB） | 每处理一个日期/批次输出 `[STAGE] {marker_name} {pct} ...` |

---

## 10. 跨模块接口

| 方向 | 接口 | 用途 |
| --- | --- | --- |
| 外部 → DataPipeline | `python -m DataPipeline --once` | 后端子进程调用 |
| 外部 → DataPipeline | `from DataPipeline import Config, DatabaseFacade, ConnectionManager, AccessTier` | 集成层（CostView / MarketView / 后端） |
| 外部 ← DataPipeline | `CostView/src/costview.py` (CostView API :8002) | TCA 查询 |
| 外部 ← DataPipeline | `CostView/src/adapters.py` (CostViewAnalyticsAdapter) | 跨模块数据适配 |
| 外部 ← DataPipeline | `market_fetch_manifest.json` (S5 输出) | 下游 MarketFetch 监听 |
| DataPipeline → Bloomberg | blpapi / xbbg | 拉取 fills、BDIB、FX、日线 |
| DataPipeline → Outdated Ticker File | `outdated_tickers.json` | 写入墓碑；下次启动加载 |

---

## 11. 总结：模块一句话

> **DataPipeline = Bloomberg 原始数据 (EMSX/BDIB) → 清洗增强 → route×timestamp 聚合 → BDIB/FX 整合成 TCA 衍生指标 → 市场状态分类 → 成交归因** 的**有状态、可重放、带护栏**的离线数据管道。它通过 **Config（路径/表名/格式）+ ConnectionManager（连接访问控制）+ DatabaseFacade（仓库聚合）+ GuardPipeline（校验/熔断/日志）** 四件套，为 EMSXView 业务层提供干净、完整、可审计的数据集。
