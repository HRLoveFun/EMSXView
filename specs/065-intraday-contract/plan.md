# 065 — 即时化契约与双仓 ADR

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-06，§4.0 数据层三层时效）
> 分支：`065-intraday-contract` · worktree：`../EMSXView-wt-065-intraday-contract`
> 依赖：DL-01（058，OrderIntent 金标准）、DL-02（060，运营库口径）· 消费者：DL-07/08/09（管道侧实施）
> 关联：ADR-0016（外部数据存储只读拆分，两仓契约测试互锁的既有做法）

## 1. 问题

- **跨仓协作未定契约**：DL-07/08/09 的管道侧实现（盘中作业 J1/J2、交易前供给表）若先行，盘中库的分文件方式、表结构、provisional 语义、读侧路由规则会按管道侧单方理解落地——漂移后本侧适配器全部返工；
- **SchemaDriftGuard 硬闸**：管道侧新表 DDL 未走 schema 注册规范时，启动前即阻断整条日更（指南 §6）——契约必须先把「表名 + 列名 + manifest 字段」冻结成可校验形态；
- **本仓库侧无写入权**（ADR-0016）：盘中库由管道唯一写入，本侧只读——读侧的「按日期路由」「provisional 降级」「守恒审计」规则需要契约显式化，否则各消费方（MarketView/CostView）各自解释。

## 2. 方案（P2 三栏）

### 2.1 理论依据

跨仓协作先定契约再实现，两仓常量由契约测试互锁（ADR-0016 既有做法）；三层时效各取所长，管道不重复订阅（tasks.md DL-06）。

### 2.2 技术方案（细化到文件与函数）

**契约数据**（`platform_data/contracts/intraday_store_contracts.py`，新建；纯数据无 IO——注意勿与既有 `intraday_contracts.py`（日内特征契约）混淆）：

- `INTRADAY_DIR_NAME = "intraday"`、`INTRADAY_DB_FILE_TEMPLATE = "intraday_YYYYMMDD.db"`（按交易日分文件）、`INTRADAY_MANIFEST_FILE_NAME = "intraday_manifest.json"`（原子写）
- `INTRADAY_TABLES: tuple[str, ...]`：6 张表名常量——`intraday_fills`、`blotter_snapshots`、`order_intent`、`route_params_snapshot`、`bars_10s_t0`、`snapshot_t0`（与父计划 §4.0 冻结条款逐字一致）
- `TABLE_COLUMNS: dict[str, tuple[str, ...]]`：每张表的列名清单（管道侧 DDL 与之对齐，SchemaDriftGuard 可校验）：
  - `intraday_fills`：J1 的 GetFills 增量经 S2/S3 同款清洗与 10 秒聚合的产物列（OrderId/RouteId/FillId/order_as_of_date/exchange_exec_time/route_as_of_time/Broker/StrategyType/algo/Exchange/equ_ticker/Side/FillShares/FillPrice/Amount/Currency + source_run_id/ingested_at）
  - `blotter_snapshots`：EMSX 导出入库（export_ts/file_name/order_key/code/exch_code/name/side/qty/ccy/status/fill_qty/pct_filled/brkr_code/create_time/pm_note/raw_row）
  - `order_intent`：DL-01 `OrderIntent` 入库形态（order_key/benchmark/close_pct/raw_note/intent_source/valid_from/export_ts/unmatched_reason/mapping_version）
  - `route_params_snapshot`：路由参数时点快照（order_id/route_id/sequence/broker/strategy_type/algo/param_json/as_of）
  - `bars_10s_t0`：J2 收盘后 bar（equ_ticker/order_as_of_date/mkt_timestamp/open/high/low/close/volume/num_trds/value/source）
  - `snapshot_t0`：J2 日快照（equ_ticker/trade_date/first_bar_time/last_bar_time/ohlc/vwap/volume/value/gap/adv 比）
- `IntradayDatasetStatus`（frozen dataclass）：manifest 每数据集条目——`dataset`、`as_of`、`watermark`（水位）、`row_count`、`status`、`last_error`
- `IntradayManifest`（frozen dataclass）：`manifest_version`、`generated_at`、`trade_date`、`datasets: list[IntradayDatasetStatus]`（与管道 freshness SLA 同口径）
- `DataFreshness`（frozen dataclass）：`dataset`、`as_of`、`lag_minutes`（读侧新鲜度可见性契约，父计划 §4.1 输出契约预留项）
- `PROVISIONAL` 语义常量与读侧路由规则常量：`READ_ROUTE_RULE = "formal-first"`（正式库已有该日就用正式数据，否则用盘中库）、`CONSERVATION_AUDIT_RULE = "diff-to-audit"`（临时与正式差异进守恒审计，沿用已解释缺口机制）、`INTRADAY_RETENTION_DAYS = 30`（保留期满整文件清理；WRITE 层禁止 DELETE，不在库内删行——v0 定值 30，磁盘压力可调，ADR 记录）

**库键登记**（`data_access/config.py`，修改；ADR-0016 的库键登记模式）：

- 模块级 `DB_INTRADAY = "intraday"`；Config 类 `INTRADAY_DIR: Path = DATA_DIR / "intraday"`、`INTRADAY_MANIFEST_FILE: Path = INTRADAY_DIR / "intraday_manifest.json"`
- `intraday_db_path(trade_date: str) -> Path`：`INTRADAY_DIR / f"intraday_{trade_date}.db"`（YYYYMMDD）

**契约测试**（`backend/api/tests/test_intraday_store_contract.py`，新建；纯结构断言，不连库）：

1. `INTRADAY_TABLES` 与父计划 §4.0 冻结条款逐字一致（6 张、名称、顺序无关的集合相等）；
2. `TABLE_COLUMNS` 覆盖全部 6 表、每表列名非空且无重复；
3. `intraday_db_path` 行为（目录、文件名模板、YYYYMMDD 原样）；
4. manifest 条目字段集与「as_of/水位/行数/状态/last_error」冻结条款一致；
5. `DataFreshness` 字段与 provisional/读侧路由/守恒审计常量存在且类型正确；
6. `order_intent` 列与 DL-01 `OrderIntent` 契约字段一一对应（跨契约对齐防漂移）。

**双 ADR**（`docs/spec/adr/0023-intraday-store-contract.md`，新建）：

- 本侧（Accepted）：盘中库定位（管道唯一写入、本侧只读）、按日期路由、provisional 语义、守恒审计、保留期 30 天定值与调整条件、`SchemaDriftGuard` 协作要求；
- 管道侧指引（文档节）：按指南 §13 的 T3/T4/T7 更新管道技术文档并同步 `docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` 副本；J1/J2 实现时以本契约为准；
- `docs/spec/memory.md` §2 与 `docs/spec/adr/README.md` 索引登记 ADR-0023（DL-03 教训：不登记会 doc-drift CI 硬阻断）。

### 2.3 检验方法（= 验收标准）

1. 两仓契约测试互锁：本侧契约测试断言镜像与冻结条款一致；管道侧以其仓库规范镜像同表（管道侧实施，本侧交付镜像源）；
2. SchemaDriftGuard 通过：管道侧注册新表 DDL（管道动作，本契约提供 `TABLE_COLUMNS` 作为校验基准）；
3. ADR 评审通过：本侧 ADR + 管道侧指引节；
4. 技术文档与契约一致：管道侧按指南 §13 更新后同步副本（管道动作，ADR 记录协作时点）；
5. 既有测试不回归（backend 全量 + boundaries + CostView 全量）。

### 2.4 本仓库交付边界（诚实记录）

本任务**不实现**管道侧任何作业（J1/J2/调度进程）、不实现本侧只读适配器（DL-07 就绪后）、不改技术文档副本（管道侧改动后触发同步）。本侧交付 = 契约镜像 + 库键登记 + 契约测试 + 双 ADR，即父计划 §4.0「联合开发流程」的「契约先行」步骤。

## 3. 规模与拆分说明

预估 diff 约 400 行（契约 ~180 + config ~15 + 测试 ~120 + ADR ~80）。DL-06 为验收原子单元（契约 + 登记 + 测试 + ADR 一次交付才能解锁管道侧），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/intraday_store_contracts.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 修改 | `data_access/config.py`（`DB_INTRADAY` / `INTRADAY_DIR` / manifest 路径 / `intraday_db_path`） |
| 新建 | `backend/api/tests/test_intraday_store_contract.py` |
| 新建 | `docs/spec/adr/0023-intraday-store-contract.md` |
| 修改 | `docs/spec/memory.md`、`docs/spec/adr/README.md`（索引登记） |
| 新建 | `specs/065-intraday-contract/plan.md`（本文件） |

范围外（不碰）：管道仓库、`docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` 副本（管道侧改动后同步）、盘中调度进程（DL-07/08）、本侧只读适配器实现（DL-07 就绪后）、任何写库路径（G0：本仓库零写入）。

## 5. 验收（P4）

| 需求（057 DL-06 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 两仓契约测试互锁 | 契约测试 1/2/6（镜像与冻结条款 + 跨契约对齐） | 待实施后回填 |
| SchemaDriftGuard 通过 | `TABLE_COLUMNS` 作为管道侧校验基准（ADR 记录） | 管道侧动作 |
| ADR 评审通过 | ADR-0023 + 索引登记 | 待实施后回填 |
| 技术文档与契约一致 | ADR 指引节（管道侧 T3/T4/T7） | 管道侧动作 |
| 既有测试不回归 | backend 全量 + boundaries + CostView 全量 | 待实施后回填 |

## 6. 本次不做

- 管道侧 J1/J2 作业与调度进程（DL-07/08，EMSXDataPipeline 仓库）；
- 本侧盘中库只读适配器与 DataFreshness 端点（DL-07 就绪后）；
- 技术文档副本同步（管道侧改动后触发）；
- 保留期定值的动态调整机制（v0 常量 30 天，ADR 记录调整条件）。
