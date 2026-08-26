# DataPipeline 业务流程梳理

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
| `pipeline_guards/` | 启动前 Schema 漂移静态扫描 + S5 前置数据质量校验 | `SchemaDriftGuard`、`EmptyBarGuard`、`BDIBCoverageGuard` |
| `circuit_breaker/` | 三态熔断、注册表、告警、重试 | `CircuitBreaker`、`RetryPolicy` |
| `monitoring/` | 运行级 JSONL 日志、RunID、概要 | `{run_id}.jsonl`、summary dict |
| `orchestration/` | 阶段基类、Stage 集合、Context、Guard 包装 | 整条管道编排入口 |
| `common/` | 时区/映射/outdated ticker 共用工具 | 跨子包复用函数 |
| `tests/` | 单元/集成/基线快照 | 基线 JSON、测试结果 |

---

## 3. 端到端业务流程

入口：`orchestration/core.py::PipelineFactory.create_daily_e2e_pipeline(skip_ingest, skip_bdib)`。`run_full_pipeline` 默认 `GUARDRAIL_ENABLED=True`，通过 `GuardPipeline` 包装 `FinancialPipeline` 注入校验/熔断/日志，异常时回退到原生管道。

```
run_full_pipeline() 入口
  └─ DataPipeline/__main__.py → orchestration/core.py::run_full_pipeline
       └─ PipelineContext 初始化（连接/配置/目标日期）
            └─ GuardPipeline.run()
                 ├─ S0 Pre-Flight 静态检查（SchemaDriftGuard）
                 └─ 阶段顺序执行：S2 → S3 → S4 → S6（默认 --once）
                      每个阶段：熔断检查 → 输入预检 → 执行 → 输出校验 → JSONL 日志
```

### 3.1 阶段清单

| Stage | 类 (位置) | 关键输入 | 关键输出 | 主要表 |
| --- | --- | --- | --- | --- |
| **S1** Ingest Excel (Legacy) | `IngestExcelStage` (`stages_ingest.py`) | Excel 文件 | `raw_fills.db` 行 | `raw_fills` |
| **S2** Process Raw Fills | `ProcessRawFillsStage` (`stages_ingest.py`) | `raw_fills.db` 当日数据 | processed_fills + `equ_ticker`（空字段 → NULL）；Exchange 空/未知直接报错；写入前校验 `order_as_of_date` 与输入日期一致 | `processed_fills`、`route_registry`（含 4 个 `count_*` 列）、`route_history`、`route_event_history`（`order_history` 是 `route_history` 的 VIEW 派生） |
| **S3** Aggregate Fills (10s) | `AggregateFillsStage` (`stages_ingest.py`) | `processed_fills` 单日 | route×timestamp 10s 桶（VWAP）；聚合前从 `route_registry` 补全 `Ticker/Side/Currency/ccy_ticker`；过滤无成交量桶 | `agg_fills_10s` |
| **S4** Generate Order Labels | `GenerateOrderLabelsStage` (`stages_ingest.py`) | `processed_fills` 单日 | 订单级标签 | `order_label`（`ticker_registry.db`） |
| **S5** Integrate BDIB | `IntegrateBDIBStage` (`stages_process.py`) | `agg_fills_10s` + Bloomberg BDIB 10s bars + FX；ticker 宇宙由 `Config.BDIB_EXCHANGE`（25 个交易所白名单；2026-07-16 业务决定仅保留 HK，剔除 8 个非分析范围市场）过滤 `ticker_repository` 决定；前置校验 `EmptyBarGuard` + `BDIBCoverageGuard` | TCA 衍生指标 | `raw_bdib`、`fill_bdib` |
| **S6** Write Manifest | `WriteManifestStage` (`stages_process.py`) | ticker registry | `market_fetch_manifest.json` | （无） |
| **S7** Daily Metrics | `CalculateDailyMetricsStage` (`stages_process.py`) | `raw_bdib` + Bloomberg bdh | ADV(5d/20d)、年化波动率、daily_vwap | `bdib_daily_summary` |
| **S8** Regime Daily Features | `RegimeDailyFeaturesStage` (`stages_analysis.py`) | 指数/BDIB 聚合 → market_index | vol/liq/trend 日级分类 | `daily_vol_regime`、`daily_liquidity_regime`、`daily_trend_regime` |
| **S9** Regime Fill Tagger | `RegimeFillTaggerStage` (`stages_analysis.py`) | `processed_fills` × `daily_*_regime` | 每笔成交的市场状态标签 | `fill_regime_labels` |
| **S10** Attribution Metrics | `AttributionMetricsStage` (`stages_analysis.py`) | `processed_fills` + `raw_bdib` + `regime` 配置 | 每笔成交的 IS/VWAP/反转指标 | `fill_attribution_metrics` |

**S1 Ingest Excel 已废弃**：数据不再从 Excel 获取，默认管道不再注册 Excel 摄入 Stage。详见 §3.2 废弃 API 清单。

**默认 `--once` 模式**：`skip_ingest=True` + `skip_bdib=True`，仅执行 S2 → S3 → S4 → S6。
**全量模式**（首跑或 force）：按上表顺序执行 S2..S10（S1 永不执行）。

### 3.1.1 S2 跨日维度修复（2026-07-03）

> **问题**：历史上 `ProcessRawFillsStage` 用 `raw_fills.source_date` 作为 `target_dates` 维度。Bloomberg 拉取按 `source_date`（拉取日）落库，一个 `source_date` 内的成交可能跨多个真实交易日（`order_as_of_date`）。S2 写入 `processed_fills` 前会校验 `order_as_of_date` 与输入日期一致，导致 13 个 `source_date` 因日期不匹配被整批拒绝——历史累计 3,600,000+ 行 raw_fills 未生成 processed_fills、agg_fills、route_registry、fill_bdib。
>
> **修复**：`target_dates` 维度从 `source_date` 改为 `raw_fills` 的 `DISTINCT order_as_of_date`，与 `processed_fills.order_as_of_date` 的真实交易日语义保持一致。

**改动点**：

| 文件 | 改动 |
| --- | --- |
| `DataPipeline/orchestration/stages_ingest.py` | `ProcessRawFillsStage` 调 `raw_reader.get_distinct_order_as_of_dates()` 替代 `get_all_source_dates()` |
| `DataPipeline/storage/repositories/raw_fills.py` | 新增 `get_distinct_order_as_of_dates()`：从 `raw_fills` 查 `DISTINCT order_as_of_date`，规范化为 `YYYYMMDD` 短格式；增强 `get_fills_for_date()`：接受 `YYYYMMDD` 输入并自动 `substr(order_as_of_date, 1, 10)` 匹配 `YYYY-MM-DD` ISO 日期，再回退到 `source_date` |
| `DataPipeline/orchestration/core.py` | 补 `import pandas as pd` |
| `DataPipeline/tests/guardrail/test_data_quality.py` | 新增 `TestStage2CrossDayProcessing` 三个回归测试：① `get_distinct_order_as_of_dates` 返回 `YYYYMMDD` 短格式；② `get_fills_for_date` 接受 `YYYYMMDD` 并匹配 ISO 日期；③ 回填后 `processed_fills` 完全覆盖 `raw_fills` 非 DFD 行（gap=0） |

**回填记录**（2026-07-03 验证）：

| 指标 | 数值 |
| --- | --- |
| 受影响 `source_date` 数量 | 13（`20250919` ~ `20251219`） |
| 自动展开 `order_as_of_date` 数量 | 69 |
| `raw_fills` 非 DFD 总行数 | 11,112,677 |
| 回填后 `processed_fills` 总行数 | 11,112,677 |
| `raw_fills` 与 `processed_fills` gap | **0** |
| 增量 `agg_fills_10s` | 1,997,504 行 |
| 增量 `order_label` | 71,435 条（覆盖 69/69 OAD） |
| 回填脚本 | `reprocess_affected_dates.py --missing-source-dates --no-s5`（已随 2026-08-26 清理归档，git 历史可查） |

**回归测试**：`DataPipeline/tests/guardrail/test_data_quality.py::TestStage2CrossDayProcessing` 3/3 通过。

### 3.1.2 BDIB 覆盖率修复（2026-07-08）

> **问题**：549 个 ticker 有成交记录（`processed_fills`）但无 BDIB 行情（`raw_bdib`），影响 TCA 分析完整性。经调查分三个根因：
> - **根因一（424 个，77%）**：`Config.BDIB_EXCHANGE` 白名单遗漏 9 个交易所（HK/CN/BZ/MM/PW/DC/IT/NZ/MUMBAI），S5 和回补脚本通过 `get_ticker_exchange_map(exchanges=Config.BDIB_EXCHANGE)` 过滤 ticker 宇宙，白名单外的 ticker 从未被传入 BDIB fetcher。
> - **根因二（108 个，20%）**：ticker 在 `processed_fills` 中有记录但 `ticker_repository` 中未注册，对 fetcher 不可见。
> - **根因三（17 个，3%）**：ticker 在白名单内且已注册，但 Bloomberg BDIB API 返回空/报错（疑似退市/停牌）。

**修复内容**：

| 文件 | 改动 |
| --- | --- |
| `DataPipeline/config.py` | `BDIB_EXCHANGE` 从 24 个扩展至 33 个交易所（追加 HK/CN/BZ/MM/PW/DC/IT/NZ/MUMBAI） |
| `DataPipeline/common/exchange_tz.py` | NZ 时区修正 `Australia/Sydney` → `Australia/Auckland`（新西兰 NZX 实际时区 UTC+12/+13） |
| `DataPipeline/orchestration/stages_process.py` | S5 前置校验追加 `BDIBCoverageGuard` 调用（紧随 `EmptyBarGuard`） |
| `DataPipeline/pipeline_guards/bdib_coverage_guard.py` | 新增：对比 `processed_fills` vs `raw_bdib` 的 `equ_ticker` 差集，按 exchange 分组报告 `ValidationViolation` |
| `scripts/ops/backfill_ticker_repository.py` | 新增：从 `processed_fills` 提取未注册 ticker 及其 Exchange，upsert 到 `ticker_repository`（支持 `--dry-run`/`--exchange`） |
| `scripts/ops/investigate_bdib_api_failures.py` | 新增：排查 17 个 API 失败 ticker，确认退市/停牌后标记 outdated tombstone（支持 `--dry-run`，需要 Bloomberg 连接） |
| `scripts/ops/backfill_bdib_by_market.py` | 新增：按市场分批编排 BDIB 回补，封装 `backfill_raw_bdib.py::run_backfill()`（支持 `--markets`/`--start`/`--end`/`--dry-run`） |

**执行记录**（2026-07-08）：

| 操作 | 结果 |
| --- | --- |
| `BDIB_EXCHANGE` 扩展 | 24 → 33 个交易所 |
| NZ 时区修正 | `Australia/Sydney` → `Australia/Auckland` |
| ticker_repository 补注册 | 108 个 ticker（涉及 20 个 exchange）成功写入 |
| `BDIBCoverageGuard` 扫描 | 检测到 549 个 ticker 有成交但无 BDIB（24 个 exchange） |
| BDIB 数据回补 | ✅ 已完成（2026-07-08）：9 个新市场 1,012 天成功，65,638,213 行写入，0 天失败 |
| BDIB 保留窗口 | Bloomberg BDIB API 历史数据保留期限：US/LN/JP/KS 约 9 个月，HK/NZ/CN/BZ 约 6 个月。超出窗口返回空数据。回补脚本默认 `--start` 动态计算为 `today - 180 天`（`Config.BDIB_API_RETENTION_DAYS`） |
| API 失败 ticker 排查 | ✅ 已完成（2026-07-08）：17 个 ticker 中 8 个确认无数据（已标记 outdated），8 个经复查 API 正常，1 个已预先标记 outdated |

### 3.1.3 BDIB 业务范围调整（2026-07-16）

> **业务决定**：2026-07-08 临时补齐的 9 个交易所中，仅 **HK（香港 HKEX）** 进入分析范围；**CN / BZ / MM / PW / DC / IT / NZ / MUMBAI** 等 8 个市场的订单不在分析范围，从 `Config.BDIB_EXCHANGE` 白名单移除。这些 ticker 不再拉取 BDIB 行情、不进入 `processed_fills` / `fill_bdib`。
>
> **数据规模**（执行清理前）：8 个市场在 `ticker_repository` 中注册 ~424 个 ticker，`fill_bdib` 中存量约 50,000,000+ 行（占 fill_bdib 总体 ~80%），主要为 2026-07-08 回补批次。`raw_bdib`（原始 10s bars）不在清理范围（与 HK 等保留市场共用，按 ticker 区分），仅清理 S5 集成后的 fill_bdib 衍生指标层。

**改动点**：

| 文件 | 改动 |
| --- | --- |
| `DataPipeline/config.py` | `BDIB_EXCHANGE` 从 33 个缩减至 25 个交易所：HK 保留在主白名单，CN / BZ / MM / PW / DC / IT / NZ / MUMBAI 8 个从白名单移除（不再拉取 BDIB） |
| `scripts/ops/backfill_bdib_by_market.py` | `NEW_MARKETS` 从 9 个市场缩减至 1 个（仅 HK）；docstring 与 `--markets` help 同步更新 |
| `scripts/ops/cleanup_excluded_exchanges_tickers.py` | 新增：分阶段清理 fill_bdib + ticker_repository 中这 8 个市场的残留数据（先 fill_bdib 后 ticker_repository） |

**清理理由**：

1. `ticker_repository` 中保留 8 个市场 ticker 会导致 S6 Manifest 输出包含这些 ticker，触发下游 `market_fetch_manifest.json` 持续包含已下线市场
2. `fill_bdib` 中保留 8 个市场 ~50M 行 TCA 衍生数据，占用 ~80% 存储空间，且无业务消费方
3. `BDIBCoverageGuard`（`pipeline_guards/bdib_coverage_guard.py`）扫描 `processed_fills` ∩ `raw_bdib` 的 equ_ticker 差集，受 `fill_bdib` 清理影响（fill_bdib 不在 guard 扫描范围），但**未来 S2 重跑这 8 个市场历史日期会持续触发 BDIBCoverageGuard**（因 `BDIB_EXCHANGE` 不再包含这些市场，ticker 无法重新拉取 BDIB），所以**必须同步清理 ticker_repository**，避免 S2 重新写入 processed_fills 时 BDIBCoverageGuard 持续告警

**执行流程**：

1. 停止 DataPipeline / backend 服务
2. 预览：`python scripts/ops/cleanup_excluded_exchanges_tickers.py --dry-run`（输出 fill_bdib 命中行数、ticker_repository 命中 ticker 数、备份路径规划）
3. 执行：`python scripts/ops/cleanup_excluded_exchanges_tickers.py --execute`（自动备份 + SHA-256 + 排他锁 + 阶段 A→B + audit + 回滚命令）
4. 验证：fill_bdib 存储释放约 80%；`raw_bdib` 仍有 8 个市场历史 BDIB 行情（与 HK 等保留 ticker 物理共存，guard 不告警）

**可调参数**：

- `--skip-fill-bdib`：仅清 ticker_repository（保留 fill_bdib 现状，但 S6 Manifest 仍会输出下线市场 ticker）
- `--skip-ticker-registry`：仅清 fill_bdib（不推荐，未来 S2 重跑历史日期时 BDIBCoverageGuard 会持续告警）
- `--reuse-backup-timestamp <YYYYMMDD_HHMMSS>`：复用历史 dry-run 的备份路径
- `--skip-backup`：跳过物理备份（依赖 DB 事务原子性）

### 3.2 Stage 内部实现概要

**S2 处理（Clean + Process）**  
`processing/fill_cleaner.clean_emsx_fills` 三步：DFD 过滤 → 时区转换（NY → local exchange tz，**空/未知 Exchange 直接报错**）→ 字段标准化。`processing/fill_processor.process_fills` 五步：algo 分类 → ccy/equ_ticker 推导 → 10s 钟时间戳 → 收盘竞价识别 → 路由 mkt_timestamp。`process_raw_fills_for_date` 再做：写 `processed_fills`、写 `route_registry`、构建 `route_history` / `route_event_history` 并 `upsert_execution_history`。`process_raw_fills_for_date` 在写入前校验 `order_as_of_date` 与输入日期一致，不一致则记录 ERROR 并标记该日期处理失败。S2 阶段的输入 `raw_fills` 由 `acquisition/bloomberg_fill_fetcher.py` + `ingestion/fill_fetch.py::FillFetch` 直接落库（内存 hash 集合 + DB hash 双层去重、SHA-256 校验、`upsert_raw_api_data` + `add_fetch_log_record`，并落 `fill_fetch_history` 审计）。

> **关于 StrategyType 空值**：部分 Broker（如 CROSSING）在 EMSX 中本就不提供 StrategyType，因此 `raw_fills.StrategyType` 为 NULL 或空字符串属于正常业务现象；`fill_processor.add_algo_column` 会将其统一归类为 `algo="other"`，不应视为数据质量问题。

> **关于 source_date 与 order_as_of_date 的语义**：`source_date` 是 S1 数据拉取/回填日期，`order_as_of_date` 是成交所在交易所的本地交易日。某些 `source_date`（特别是历史回填批次）可能包含多个 `order_as_of_date` 的成交。当 `process_raw_fills_for_date` 以 `source_date` 为输入时，若其对应记录的 `order_as_of_date` 不完全一致，S2 日期一致性校验会拒绝整批写入，这是导致 `raw_fills.db` 与 `processed_fills.db` 行数可能不一致的主要原因之一。


**S3 聚合**  
`processing/fill_aggregator.generate_agg_fills_10s`：按 `(OrderId, RouteId, mkt_timestamp)` groupby → 唯一值列 / `sum(FillShares)` / VWAP。由于 `processed_fills` 的 schema 已将 `Ticker`、`Side`、`Currency`、`ccy_ticker` 去冗余，S3 在聚合前通过 `LEFT JOIN route_registry` 从 `equ_ticker`/`ccy_ticker` 推导补回这四列（与 `v_processed_fills_legacy` 视图保持一致）。VWAP 计算仅使用 `FillShares>0` 的记录；无成交量桶（`FillShares` 总和为 0）被丢弃，避免 `FillPrice` 出现单条 `NULL`。

**S4 Order Label**  
`processing/order_label.generate_order_label_incremental`：逐日处理（避免 OOM），累计标签集向后传递；写入 `ticker_registry.db` 中的 `order_label` 表。

**S5 BDIB 整合（TCA）**  
`acquisition/bdib_fetcher.fetch_bdib_for_fills`：并行拉 BDIB 10s bars；`processing/fill_bdib_integrated.integrate_fills_bdib_for_date`：在内存中 left-join BDIB + FX + 每日指标，并 `_compute_derived_metrics`（VWAP slippage、Arrival slippage、PX diff、9 个累积 TCA 列、累计 vol/价值、tracking error、info ratio、波动率）。结果写入 `fill_bdib.db`。

**S6 Manifest**  
`analysis/downstream_interface.write_manifest`：序列化当前激活的 equ/ccy ticker 列表到 `market_fetch_manifest.json`，供下游 MarketFetch 监听。

**S7 Daily Metrics**  
`processing/daily_metrics_calculator.CalculateDailyMetrics.run_for_date`：并行 chunk 拉 `PX_VOLUME` / `VOLATILITY_30D` / `PX_LAST`，与 raw BDIB 10s bars 计算 ADV(5d/20d)、日内 VWAP、年化波动率。增量跳过已写入 `bdib_daily_summary` 的日期。

**S8 Regime 分类**  
- `regime/market_index_loader.load_market_index`：拉取指数/参考数据  
- `regime/vol_regime.classify`：VIX 阈值（缺则降级为 realized_vol_zscore）  
- `regime/liquidity_regime.classify`：换手率 z-score（lookback 60d）  
- `regime/trend_regime.classify`：MA + RSI 组合  
- 所有调用包在 `run_journal` contextmanager 中，写入 `audit_pipeline_runs`。

**S9 Fill Tagging**  
`regime/fill_regime_tagger.tag_fills`：从 `processed_fills` 拉区间数据 → `derive_market_code`（EUR 折为 `EU`）→ 关联三种 regime → 检查 `ref_macro_event_calendar` 标记 macro window → 用 `assign_time_bucket`（仅 5 个启用市场）打 `time_bucket` → UPSERT 到 `fill_regime_labels`。

**S10 Attribution**  
`analysis/attribution/writer.run_metrics`：拉 1min bar panel → 计算 `arrival_px` / `interval_vwap` / `mid_at_fill` / `mid+N` → `slippage_bps`（IS / VWAP） + `reversal_bps`（1m/5m/30m） → `pct_adv`（与 `bdib_daily_summary.adv_20d` 关联）→ UPSERT `fill_attribution_metrics`。完成后写 `audit_pipeline_runs` + `audit_research_snapshots`（SHA-256 快照）。

---

## 3.2 废弃 API 清单（Deprecated — v2.0 移除）

> 业务约束：**数据已不再从 Excel 获取**。下表所列 API 仅作历史归档兼容保留，调用时均会发出 `DeprecationWarning`（Python 标准 `warnings` 模块）并在关键路径写 `logger.warning`。请迁移至 **Bloomberg API 摄入（`fill_fetch.py`）**。

| 符号 | 位置 | 状态 | 替代方案 |
| --- | --- | --- | --- |
| `IngestExcelStage`（S1 Ingest Excel） | `orchestration/stages_ingest.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch`（Bloomberg API） |
| `run_ingest()` | `orchestration/core.py` | ❌ 已废弃（v2.0 移除） | `run_full_pipeline(skip_ingest=True)` |
| `ingest_excel_file()` | `ingestion/fill_ingestion.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch.fetch_and_store()` |
| `ingest_all_excel_files()` | `ingestion/fill_ingestion.py` | ❌ 已废弃（v2.0 移除） | `fill_fetch.FillFetch` 批量拉取 |

**废弃标记层级**：

1. **模块文档**：在 `fill_ingestion.py` 文件头标注 `Mode 1 (DEPRECATED — v2.0 移除)`。
2. **类/函数 docstring**：使用 Sphinx `.. deprecated::` 指令。
3. **运行时警告**：调用时发出 `DeprecationWarning`（`stacklevel=2`，定位到调用方）。
4. **关键路径日志**：`create_daily_e2e_pipeline(skip_ingest=False)` 注册 S1 前写 `logger.warning(...)`。
5. **管道默认值保护**：`PipelineFactory.create_daily_e2e_pipeline` 默认 `skip_ingest=True`，S1 在日常运行中不执行。

**升级路径**：

- 任何调用 `run_ingest()` / `ingest_excel_file()` / `ingest_all_excel_files()` 的脚本需迁移到 `fill_fetch.py`。
- 不再有"全量模式（首跑或 force）"会执行 S1；`run_full_pipeline` 永远跳过 Excel 摄入。
- v2.0 将删除上述四个符号；届时调用将报 `AttributeError`，提醒升级。

---

## 3.3 S2 字段语义

### 3.3.1 时区语义

S2 写入 4 张表的所有时间列统一归为 3 类，**严禁混用**：

| 类型 | 包含列 | 时区 | 字符串格式 | 样例 |
| --- | --- | --- | --- | --- |
| **原始 NY tz** | `DateTimeOfFill` / `NyOrderCreateAsOfDateTime` / `NyTranCreateAsOfDateTime` | `America/New_York` | ISO8601 **含 tz 后缀** | `2026-04-16T11:49:59-04:00` |
| **派生 local exchange tz** | `local_fill_datetime` / `mkt_timestamp` / `order_as_of_date` / `exchange_exec_time` / `route_as_of_time` / `first_fill_time` / `last_fill_time` / `event_timestamp` | `Config.EXCHANGE_TZ_MAP[Exchange]`（按订单所属交易所） | ISO8601 / `YYYYMMDD` / `HH:MM:SS` **无 tz 后缀** | `2026-04-16T23:49:59`、`20260416`、`09:49:59` |
| **UTC** | `source_refreshed_at` | `UTC` | ISO8601 **含 `+00:00` 后缀** | `2026-06-18T03:41:29+00:00` |

**实施细节**：

- `local_fill_datetime` 在 `processing/fill_cleaner.derive_exchange_times` 中由 `batch_convert_ny_to_local(parsed, exchange_col)` 生成（10-50× vectorized 性能）。**空/未知 Exchange code 不再回退到 NY 时间，直接抛出 `ValueError`，必须在 `EXCHANGE_TIMEZONE` 补齐映射或修复上游数据。**
- `first_fill_time` / `last_fill_time` 在 `ingestion/fill_ingestion._first_last_event_time` 中**统一用 `local_fill_datetime`**。先 `pd.to_datetime(..., errors="coerce")` 解析为 datetime 对象，再 `min/max` 后用 `strftime("%Y-%m-%dT%H:%M:%S")` 输出。
- `source_refreshed_at` 用 `datetime.now(timezone.utc).isoformat(timespec="seconds")`。
- `event_timestamp`（`route_event_history`）统一为 `local_fill_datetime`。

### 3.3.2 `LimitPrice` / `StopPrice` 默认值策略

- **缺失/无效 → NULL（非 `"0"`）**。下游消费方（`CostView/src/tca_query_builder.py`）使用 `>0` 过滤 0 值。
- **列类型 `TEXT` → `REAL`**：`inline_ddl.init_raw_fills_schema` 将两列改为 `REAL`，与 `processed_fills.FillPrice` / `FillShares` 一致。`COLUMN_TYPE_MAP` 同步标注 `LimitPrice: REAL` / `StopPrice: REAL`。已有 `raw_fills.db` 首次启动时由 `inline_ddl._migrate_raw_fills_column_types` 自动升级（CREATE NEW + COPY + DROP + RENAME 模式，幂等，单事务，空字符串→NULL）；同时预留 `migrations/raw_fills/v1_to_v2.sql` 供 `MigrationRunner` 未来激活。
- `_parse_fill_messages` 内部使用 `getElementAsFloat` 抓取，异常/缺失 → `None`。

### 3.3.3 `processed_fills` 主键与 `key_columns` 对齐

- **DDL 主键**：`PRIMARY KEY (OrderId, RouteId, FillId, order_as_of_date)`（`storage/schema/inline_ddl.init_processed_fills_schema` line 285）。
- **`upsert_processed_fills` 的 `key_columns`**：`["OrderId", "RouteId", "FillId", "order_as_of_date"]`，与 DDL 主键 4 元组对齐。当前 `_upsert_fixed_schema` 实际未用 `key_columns` 生成 `ON CONFLICT`（依赖 SQLite 唯一键判重），运行时行为不变；目的是与 schema 语义保持一致，避免未来 SQLite 升级时行为漂移。

### 3.3.4 `route_registry` count 列

- **DDL 包含 4 列**：`count_fill` / `count_broker` / `count_algo` / `count_trader`（`storage/schema/columns.ROUTE_REGISTRY_COLUMNS` + `COLUMN_TYPE_MAP` 标 INTEGER）。
- `process_raw_fills_for_date` 在 `upsert_route_registry` 之前对 `processed` 按 `(OrderId, RouteId)` groupby 计算 `count_fill = nunique(FillId)` / `count_broker = nunique(Broker)` / `count_algo = nunique(algo)` / `count_trader = nunique(TraderName)`，用 `merge` 写入 `processed_for_registry` 副本，再调 `upsert_route_registry(processed_for_registry)`。

### 3.3.5 `route_history` / `route_event_history` 字段来源

- **保留字段**：`equ_ticker` / `ccy_ticker` / `Side`（**必须保留**）。证据：`CostView/src/tca_query_builder.py:129, 146-148, 183-185, 195, 217` 全部 `LEFT JOIN route_registry` 或 `route_history` 取这 3 列做高频 JOIN key。`route_event_history` 同样保留以做调试追溯。
- 所有字段（`equ_ticker` / `ccy_ticker` / `Side` / `Broker` / `algo` / `TraderName` / `Exchange`）直接从 `processed_df` 自身取（`groupby` 取 `group.get(...)` 与 `itertuples` 取 `row._asdict()[...]`），与 `event_records` 同源。

### 3.3.6 `processed_fills.equ_ticker` 空字段处理

- `add_equity_ticker` 拼接规则：`(Ticker + " " + Exchange + " Equity").str.strip()`。
- **空字段处理**：当 `Ticker` 或 `Exchange` 为空/空白时，通过 `blank_mask`（覆盖 `isna()` / `str.strip()==""` / 字符串 `"nan"`/`"none"`）将 `df.loc[blank_mask, "equ_ticker"] = np.nan` 替换为 NULL，并记录 ERROR；若启用 `Config.STRICT_MISSING_TICKER_VALIDATION` 则直接抛 `ValueError` 阻止该日期入库。
- **EUR composite ticker**：缓存优先策略：① 先查本地 `eur_composite_ticker_cache` → ② 缓存未命中 → 查询 Bloomberg（`xbbg blp.bdp` chunked + 单 chunk 独立线程超时）→ ③ BBG 结果回写缓存 → ④ 仍未命中 → 保留原始拼接 equ_ticker（fallback），记录 warning。
- **单元测试**：`DataPipeline/tests/guardrail/test_add_equity_ticker.py` 8 个用例覆盖空 Exchange / None Exchange / NaN Exchange / 空 Ticker / 正常拼接 / KRW zfill / EUR 缓存全 miss fallback / EUR 部分命中；`DataPipeline/tests/guardrail/test_data_quality.py` 覆盖 Exchange 空值/未知报错、日期一致性校验、route_registry 列补全、零股 VWAP 过滤。

### 3.3.7 raw_fills 派生列状态

- **raw_fills DDL 派生/元数据列**（`inline_ddl.init_raw_fills_schema`）：

  | 列 | 状态 | 说明 |
  | --- | --- | --- |
  | `order_as_of_date` | ✅ NOT NULL（v4 约束） | S2 分区索引基础，按日期归档；业务语义为每个订单都必须有执行日期 |
  | `exchange_exec_time` | ✅ 保留 | 派生 local exchange 时间（`HH:MM:SS`），由 `derive_exchange_times` 计算 |
  | `ingested_at` | ⚠️ deprecated | 与 `fetched_at` 重复，v3.0 删除（保留至 2.x 向后兼容） |

  > 注：`order_as_of_time` / `route_as_of_time` / `local_fill_datetime` 在 raw_fills DDL 中**不存在**（仅 `processed_fills` 及下游表才有），故不列入本表。

- **同步点**：`CostView/tests/test_tca_query_service.py:198-208` fixture + `scripts/ops/import_excel_fills.py:818-845` legacy DDL 已同步列类型与 deprecated 注释。
- **核心语义**：`raw_fills` 是 BBG 原始落地区，**不做派生**。审计由 `source_date` / `fetched_at` + `ingestion_log` 表承担，不在数据列上混入派生字段。

### 3.3.8 raw_fills 主键、fetch_log 软状态与 order_as_of_date NOT NULL

- **raw_fills PK**：`PRIMARY KEY (OrderId, RouteId, FillId, source_date)`（4 元组）。同 `OrderId` 跨日 fetch 时自然分离为新行，不再覆盖。
- **fetch_log 软状态机制**：`status` 字段使用 CHECK 约束 `('fetched','deprecated','superseded','failed')`。同 `source_date` 多次 fetch 时，`add_fetch_log_record` 自动软标记旧行 `deprecated`，与 `UNIQUE(source_date, data_hash)` 共同实现 latest-wins 语义同时保留审计。
- **order_as_of_date NOT NULL 约束**（v4）：业务语义为每个订单都必须有执行日期。违反约束的 INSERT 会被 DB 拒绝，必须在 `upsert_raw_api_data` / `clean_emsx_fills` 处保证 `order_as_of_date` 计算成功（`EXCHANGE_TIMEZONE` 字典必须含 Bloomberg 实际 Exchange code）。
- **迁移路径**：`inline_ddl._migrate_raw_fills_column_types` + `_migrate_raw_fills_pk` 提供幂等自动升级（首次启动触发，覆盖 v1/v2/v3 变更）。历史显式迁移脚本 `migrate_raw_fills_to_v3.py` / `apply_v3_to_v4.py` 已随 2026-08-26 清理归档（自动升级覆盖同等变更）。SQL 版本链：`migrations/raw_fills/v0_to_v1.sql` / `v1_to_v2.sql` / `v2_to_v3.sql` / `v3_to_v4.sql`。
- **raw_fills 写入 NaN/NA 修复**：`upsert_raw_api_data` 在 `pd.DataFrame(fills)` 之后反查原始字典，恢复被 pandas 误转为 NaN 的字符串 `"NA"`（Exchange 荷兰 Amsterdam / Ticker National Bank of Canada BBG mnemonic）。2026-06 两轮修复所用脚本 `fix_raw_fills_null_exchange.py` / `fix_raw_fills_null_ticker_national_bank.py` 已完成使命并归档；现行防护即 upsert 反查逻辑本身。
- **EUR equ_ticker 历史回填**：2025-09 ~ 2026-06 缓存建立前的受影响 source_date 已通过一次性回填修复（脚本 `backfill_eur_ticker.py` 已归档；分析见 `docs/archive/2026-06-29/eur_ticker_issue_analysis.md`）。
- **oaod/eet 历史回填**：`scripts/ops/backfill_raw_fills_oaod_eet.py` 用 `derive_exchange_times` 内存重算逐行 UPDATE，回填 `order_as_of_date` 与 `exchange_exec_time` 字段 NULL 行。

### 3.3.9 EUR equ_ticker 历史回填

- **历史回填脚本**：`scripts/backfill_eur_ticker.py`（已随 2026-08-26 清理归档，git 历史可查）对 2025-09 ~ 2026-06 期间（缓存建立前）的受影响 source_date 重跑 S2-S4，恢复 EUR 股票的 `equ_ticker` 字段。回填前自动备份，支持 `--dry-run`、`--retention` 自动清理旧备份。
- **处理结果**（2026-06-30 验证）：EUR 行 `equ_ticker NULL` 率从 93.17% 降至 10.13%（残留 NULL 仅来自 raw_fills 中 `Exchange IS NULL` 的行）；EU Equity 命中行从 6.83% 升至 88.75%。
- **详细分析**：[`docs/archive/2026-06-29/eur_ticker_issue_analysis.md`](../../docs/archive/2026-06-29/eur_ticker_issue_analysis.md)（📦 已归档，2026-07-02 修复完成）。

---

## 4. 护栏（GuardPipeline）子系统

> 目标：在不侵入现有 `FinancialPipeline` 的前提下注入校验/熔断/日志。

```
FinancialPipeline  ──wrap──▶  GuardPipeline.run(context)
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
| `SchemaDriftGuard` | `pipeline_guards/schema_drift_guard.py` | 扫描 DDL 与代码层写入路径的 schema 漂移；4 类检测（PRIMARY_KEY_TYPE_MISMATCH / COLUMN_MISSING_IN_DDL / COLUMN_MISSING_IN_CODE / VALUE_TYPE_MISMATCH）；白名单降级 INFO，未知漂移 ERROR 阻断 + critical 告警；仅检查不自动修复 |
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
| S2–S10 | Internal | STRICT | ERROR 累加达阈值触发熔断；CRITICAL 立即熔断 |

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
| `processed_raw_bdib` | `processed_raw_bdib.db` | `processed_raw_bdib` | S5（主路径仍双写；回补路径 A8 后已退役，`PROCESSED_RAW_BDIB_ENABLED=1` 控制启用） | — |
| `fill_bdib` | `fill_bdib.db` | `fill_bdib` | S4 | CostView |
| `regime` | `regime.db` | `daily_vol_regime`、`daily_liquidity_regime`、`daily_trend_regime`、`fill_regime_labels`、`fill_attribution_metrics`、`audit_regime_config_versions`、`audit_pipeline_runs`、`audit_research_snapshots`、`ref_*` | S7/S8/S9 | S8/S9/CostView |
| `fill_fetch_history` | `fill_fetch_history.db` | `fill_fetch_history` | Fetcher | 审计 |
| `execution_history` | `execution_history.db` | `route_registry`、`route_history`、`route_event_history`（`order_history` 是 `route_history` 的 VIEW 派生，无独立物理表） | S1（写 `route_history` / `route_event_history`） | CostView |
| `ticker_registry` | `ticker_registry.db` | `equ_ticker_registry`、`ccy_ticker_registry`、`order_label`、`eur_composite_ticker_cache` | S1/S3 | S4/S5/S6 |

> 数据根目录由 `EMSXVIEW_DATA_DIR` 环境变量覆盖；默认 `CostView/data`（向后兼容）。

### 5.2 连接管理关键约定

- `AccessTier.READ`：禁止 INSERT/UPDATE/DELETE；同一线程内通过 `threading.local` 缓存连接（避免每次 ~50µs 重建开销）。
- `AccessTier.WRITE`：每次新建连接；自动应用 `journal_mode=WAL` + `foreign_keys=ON` + `busy_timeout=30s`。
- 全部连接由 `AccessControlledConnection` 包装，在 `execute()` 时按 SQL 正则分类做权限校验。
- 迁移统一走 `DataPipeline/storage/schema/migrations/apply.py` 与 `migration_framework.MigrationRunner`：读取 `PRAGMA user_version`，按 `vN_to_vN+1.sql` 顺序应用，跨进程排他锁（`os.O_CREAT | os.O_EXCL` 原子锁文件）。`_EXPECTED_CURRENT`：`raw_fills=v4` / `processed_fills=v1` / `raw_bdib=v2` / `processed_raw_bdib=v1` / `fill_bdib=v1` / `regime=v3`。

### 5.3 仓库分层

- `storage/connection.py` → 连接访问控制
- `storage/facade.py` → 9 个仓库聚合入口
- `storage/repositories/*.py` → 8 个表领域（fills、raw_fills、market_data、integrated、regime、fetch_history 等）
- `storage/schema/columns.py` → EMSX 列定义 + RAW_BDIB 列定义
- `storage/schema/migrations/` → forward-only DDL 链（`raw_fills/` / `processed_fills/` / `raw_bdib/` / `fill_bdib/` / `processed_raw_bdib/` 子目录）

---

## 6. 横切关注点（Cross-Cutting）

| 关注点 | 实现位置 | 说明 |
| --- | --- | --- |
| **时区** | `common/exchange_tz.py` | `NY_TZ` + `batch_convert_ny_to_local`，按 Exchange 分组 vectorized 转换（10-50× 单行调用）。`EXCHANGE_TIMEZONE` 字典映射 Bloomberg 交易所代码至 IANA 时区（含 `MUMBAI`/`BSE`/`NSE` 印度交易所）。所有 S1 派生时间列统一为 local exchange tz（无 tz 后缀），`source_refreshed_at` 统一为 UTC（含 `+00:00` 后缀）。详见 **§3.3.1 时区语义**。 |
| **Algo 分类** | `common/mapping.py` | VWAP / TWAP / POV / Close / 收盘竞价时间映射 |
| **Outdated Ticker** | `common/outdated_tickers.py` | 基于 `outdated_tickers.json` 持久化墓碑；BDIB 拉取与 Manifest 生成时跳过；`Cannot find exchange info` 时自动登记 |
| **过期股票处理** | `processing/fill_processor._fetch_composite_tickers` | EUR 复合代码 `cache-first`（`eur_composite_ticker_cache` 表）+ xbbg `blp.bdp` chunked + 单 chunk 独立线程超时 |
| **进度报告** | 各 Stage 内 `print(f"[STAGE] {marker_name} {pct} ...", flush=True)` | 防止前端因长任务无输出误判 stalled |
| **去重** | `FillFetch._preload_known_hashes` + `compute_data_hash` | 内存 hash set + DB hash 双层 |
| **FX 转换** | `acquisition/fx_fetcher.py` + `storage/repositories/fx_rates.py` | `USD{ccy} Curncy` 取 PX_LAST 并取倒数（`fx_rate` = USD per 1 单位本币）。拉取链（fx-rate-persistence）：S5 注入 `fx_repo` 后 **查 `fx_rates` 表优先**（命中零配额消耗，先于额度暂停检查）→ miss 才拉 Bloomberg → 成功即落表（幂等 REPLACE，`px_last` 双存）；失败/暂停降级：表内 ≤目标日期 最近已知 → 内存缓存 → 1.0 兜底（降级值不落表）。表初始化/刷新用 `scripts/ops/backfill_fx_rates.py`（`--seed` 从 fill_bdib 反推 / `--refetch` 按日期范围重拉） |
| **交易日期防护** | `bdib_fetcher._is_safe_bdib_query_date` | 拒未来日 + 周末/节假日 + 距当前不足 BDIB_LATEST_READY_HOUR_LOCAL |
| **Exchange 空值/未知防护** | `common/exchange_tz.batch_convert_ny_to_local` + `fill_cleaner.derive_exchange_times` | 空/未知 Exchange 不再回退到 NY 时间，直接抛 `ValueError` 阻止错误日期入库 |
| **S2 日期一致性校验** | `ingestion/fill_ingestion.process_raw_fills_for_date` | 写入 `processed_fills` 前校验 `order_as_of_date` 与输入日期一致，不一致则标记失败 |
| **S3 列补全** | `processing/fill_aggregator.generate_agg_fills_10s` | 从 `route_registry` 补回 `Ticker/Side/Currency/ccy_ticker`，保持 `processed_fills` 去冗余设计 |
| **零股 VWAP 过滤** | `processing/fill_aggregator.generate_agg_fills_10s` | `FillShares=0` 不贡献 VWAP；无成交量桶直接丢弃，避免 `FillPrice` 单条 `NULL` |
| **KRW 补零** | `processing/fill_processor.add_equity_ticker` | KRW 股票 Ticker 自动 zfill(6) |
| **荷兰 NA 修复** | `processing/fill_cleaner.normalize_fill_columns` | pandas 把字符串 `"NA"` 解析为 NaN，显式还原为 `"NA"` |
| **归档加密** | （已移除） | 原 `storage/crypto.py` + `access_impl.py` 加密列特性无消费者，随 2026-08-26 清理移除（ADR-0014）；如需启用从 git 历史恢复 |
| **备份/归档** | `storage/backup.py` / `storage/archiver.py` | 时间戳 `.bak` 文件 / 长期冷存 |
| **审计** | `audit_pipeline_runs`、`audit_research_snapshots` | 每次 stage 运行 SHA-256 快照，便于复现 |
| **NaN/'NA' 恢复** | `storage/repositories/raw_fills.py::upsert_raw_api_data` | `pd.DataFrame(fills)` 后从原始字典反查字符串 `"NA"`（Exchange 荷兰 / Ticker National Bank of Canada），防止永久化到 DB |
| **DuckDB 查询** | `storage/market_store.py` | BDIB Parquet/DuckDB 双引擎读路径（`BDIB_QUERY_ENGINE` 控制） |
| **S2 target_date 维度** | `raw_fills.get_distinct_order_as_of_dates` + `ProcessRawFillsStage` | 维度固定为 `order_as_of_date`（真实交易日，`YYYYMMDD`），**禁止**回退到 `source_date`（拉取日）；S2 日期一致性校验在 `process_raw_fills_for_date` 写入前执行 |

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
processed_fills (S2) ─── 同事务写入 ───┐                         │
  │  22 列                                │  execution_history  │
  │                                       │  (route/event；order │
  │                                       │   为 route 的 VIEW)  │
  ▼                                       ▼                     │
agg_fills_10s (S3)                    execution_history.db      │
  │  groupby(OrderId, RouteId, mkt_ts)                           │
  │  VWAP + FillShares sum                                       │
  ▼                                                             │
order_label (S4) ── ticker_registry.db ─┐                       │
  │  订单级标签 (side/amount/algo)     │  BDIB                  │
  │                                     ▼                       │
  │  (BDIB 10s bars via xbbg)        raw_bdib (S5 拉取阶段)     │
  │  + FX rates                         │  10 列原始 Bloomberg   │
  │                                     │  衍生字段内存计算      │
  │                                     ▼                       │
  │                                  raw_bdib (10s bars)        │
  │                                     │                       │
  │                                     ▼                       │
  │                            fill_bdib (S5 集成阶段)           │
  │                              LEFT JOIN agg_fills_10s          │
  │                              + FX + 日级指标                 │
  │                              + 9 个累积 TCA 列              │
  │                                                             │
  │  bdib_daily_summary (S7) ─────────── PX_VOLUME /             │
  │                                     VOLATILITY_30D /         │
  │                                     PX_LAST + 日内 VWAP      │
  │                                                             │
  │  daily_market_index (S8) ─── 指数/参考数据                  │
  │     │                                                        │
  │     ▼                                                        │
  │  daily_vol_regime     daily_liquidity_regime     daily_trend_regime
  │                                                             │
  │  fill_regime_labels (S9) ── 三种 regime × macro × time_bucket
  │                                                             │
  │  raw_bdib 1min panels (S10) ── arrival_px / interval_vwap   │
  │     │                            / mid_at_fill / mid+N       │
  │     ▼                                                        │
  │  fill_attribution_metrics (S10) ── IS / VWAP / reversal bps  │
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
| BDIB | `BDIB_EXCHANGE` | 25 个交易所（含 HK 业务保留，2026-07-16 后从 33 个缩减） | 拉取白名单 |
| BDIB | `BDIB_LATEST_READY_HOUR_LOCAL` | 8 | 当日 BDIB 安全就绪小时 |
| BDIB | `BDIB_PARQUET_ENABLED` | false | Parquet 双写 (Phase A) |
| BDIB | `BDIB_PARQUET_DIR` | `data/market/bdib_10s` | Parquet 目录 |
| BDIB | `BDIB_QUERY_ENGINE` | `duckdb` | `sqlite` / `duckdb` |
| 分区 | `PARTITION_DUAL_WRITE` | false | 分区双写 (Phase B) |
| 分区 | `PARTITION_READ_NEW` | false | 读新分区 |
| 护栏 | `GUARDRAIL_ENABLED` | true | 护栏总开关 |
| 护栏 | `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD` | 3 | 熔断阈值 |
| 护栏 | `GUARDRAIL_RETRY_MAX` | 3 | Fetcher（外部 Bloomberg 拉取）重试次数 |
| 护栏 | `GUARDRAIL_VALIDATION_STRICT_MODE` | true | 全局严格模式 |
| 护栏 | `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR` | false | 校验降级放行 |
| 护栏 | `STRICT_MISSING_TICKER_VALIDATION` | false | 缺失 Ticker/Exchange 时直接报错，阻止空 `equ_ticker` 流入下游 |
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
| Bloomberg ErrorResponse / ErrorInfo（如权限撤销） | `BloombergFillFetcher._fetch_fills_once` | 检测 `ErrorResponse`/`ErrorInfo` 消息，提取 ErrorCode/ErrorMsg 抛出 `EMSXRequestError`；`fetch_day` except 块捕获后 `success=False`，不再静默返回 0 行伪装成功。`_parse_fill_messages` 解析异常由 `except: pass` 改为 `logger.warning` |
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
| 外部 ← DataPipeline | `platform_data.adapters.get_tca_query_service()`（读取 `tca_route_summary` 汇总表） | 跨模块 TCA 数据适配 |
| 外部 ← DataPipeline | `market_fetch_manifest.json` (S5 输出) | 下游 MarketFetch 监听 |
| DataPipeline → Bloomberg | blpapi / xbbg | 拉取 fills、BDIB、FX、日线 |
| DataPipeline → Outdated Ticker File | `outdated_tickers.json` | 写入墓碑；下次启动加载 |

---

## 11. 运维脚本（`scripts/ops/` 与 `scripts/`）

| 脚本 | 用途 |
| --- | --- |

> 注：S2 跨日修复与 Phase A/B 迁移期的一次性脚本（`reprocess_affected_dates` / `cleanup_processed_fills_mismatches` / `analyze_processed_fills_nulls` / `migrate_raw_fills_to_v3` / `apply_v3_to_v4` / `fix_raw_fills_null_*` / `cleanup_orphan_processed_fills` / `verify_*` / `backfill_fill_bdib_*` / `backfill_daily_metrics` / `cleanup_raw_bdib_empty_bars` / `backfill_eur_ticker` 及 devtools、diagnose 诊断件）已于 2026-08-26 死代码清理中移除（ADR-0014），需要时从 git 历史恢复。
>
| `scripts/ops/backfill_raw_fills_oaod_eet.py` | 回填 `raw_fills.order_as_of_date` 与 `exchange_exec_time` NULL 行（`derive_exchange_times` 内存重算逐行 UPDATE） |
| `scripts/ops/cleanup-logs.ps1` | 清理历史日志 |
| `scripts/ops/service-manager.ps1` | DataPipeline 服务管理 |

---

## 12. 总结：模块一句话

> **DataPipeline = Bloomberg 原始数据 (EMSX/BDIB) → 清洗增强 → route×timestamp 聚合 → BDIB/FX 整合成 TCA 衍生指标 → 市场状态分类 → 成交归因** 的**有状态、可重放、带护栏**的离线数据管道。它通过 **Config（路径/表名/格式）+ ConnectionManager（连接访问控制）+ DatabaseFacade（仓库聚合）+ GuardPipeline（校验/熔断/日志）** 四件套，为 EMSXView 业务层提供干净、完整、可审计的数据集。
