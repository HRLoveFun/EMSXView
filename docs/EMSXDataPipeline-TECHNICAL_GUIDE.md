# EMSXDataPipeline 技术说明（外部 Agent 版）

> L2 | 权威：上游管道架构与数据链路的同步副本（真相源在 EMSXDataPipeline 仓库） | 不权威：本仓取数实现（见 `docs/spec/data-domain.md`）

> **副本说明（EMSXView 仓库侧）**
>
> - 本文件是独立私有仓库 **EMSXDataPipeline** 的技术说明 `docs/TECHNICAL_GUIDE.md` 的**同步副本**，保留于本仓库（EMSXView），供仅有本仓库访问权限的外部 Agent 了解该数据管道仓库。
> - **真相源**：EMSXDataPipeline 仓库内同名文档；其 §13 维护机制（每周例行核对 + 触发式不定期更新）在该仓库执行。本仓库副本为最近同步快照——真相源更新后应**整体覆盖同步**本文件（除本说明块外正文与真相源逐字一致），并更新下方同步状态。
> - 同步状态：真相源 `v1.0（2026-10-20）`，本副本同步于 `2026-10-20`。
> - **占位符语义**：文中 `<REPO_ROOT>` / `<DATA_DIR>` / `<LOG_DIR>` 均为 **EMSXDataPipeline 仓库语境**的占位符（定义见该仓库 README），**不是**本仓库 `docs/index.md` §7 的占位符；其中 `<DATA_DIR>` 与本仓库 `${EMSXVIEW_DATA_DIR}` 指向同一数据根——读写两侧数据根同源是两仓间的硬约束（§1.2 / §1.3）。
> - 本副本不改变两仓边界：EMSXView 仍是只读消费方，禁止 `import DataPipeline.*`；两仓交互方式见本文 §1.3 与本仓库 `docs/spec/data-domain.md`。

> **文档目的**：面向**无本仓库源码访问权限**的外部 AI Agent / 工程协作者，完整呈现项目定位、总体架构、数据获取与处理端到端流程、校验与存储机制、交易前（pre-trade）数据供给链路及其优化路径。读完本文档即可在不读源码的前提下准确理解系统并据此开展分析或优化。
>
> **免责声明（继承仓库 README）**：本项目为作者个人独立开发的 side project，与任何机构无关；与 Bloomberg L.P. 无任何关联或背书；仓库不含任何真实成交、行情或账户数据；实际运行需自行具备合法的 Bloomberg 终端与数据授权。
>
> **路径占位符**（与仓库 README 约定一致，禁止写死机器路径）：
> `<REPO_ROOT>` = 仓库根目录；`<DATA_DIR>` = 数据根目录（环境变量 `EMSXVIEW_DATA_DIR`，未设置时取 `Config.DEFAULT_DATA_DIR`，为用户主目录下的 `emsx_data` 占位目录）；`<LOG_DIR>` = `<REPO_ROOT>/logs`。
>
> **真相源关系**：本文是「导览与整合层」文档。代码级单一事实源：路径/表名/开关 → `DataPipeline/config.py`；通道阈值 → `DataPipeline/access_guide.py`；阶段语义 → `DataPipeline/BUSINESS_FLOW.md`；表结构 → `docs/DATABASE_MANUAL.md`。本文与其冲突时，以真相源为准并按 §13 维护机制修订本文。

| 项 | 值 |
|---|---|
| 文档版本 | 1.0（2026-10-20 首版） |
| 对应项目版本 | `1.1.0`（`pyproject.toml`） |
| 读者 | 无源码访问权限的外部 Agent / 协作者 |
| 更新机制 | 见 §13（每周例行 + 触发式不定期） |

---

## 1. 项目定位与系统边界

### 1.1 一句话定位

EMSXDataPipeline 是一个**独立的数据维护项目**：从 Bloomberg EMSX（成交 `GetFills`）与 BDIB（10 秒行情）拉取数据，清洗、聚合、打标，产出 TCA（交易成本分析）/ 市场状态（regime）/ 执行归因结果。它是下游所有 SQLite 库与 Parquet 数据集的**唯一写入方**；下游业务应用与前端控制台以 SQLite `mode=ro` 只读消费。

### 1.2 唯一写入方契约（系统最高边界）

| 约束 | 内容 |
|---|---|
| 唯一写入方 | 本仓库的数据管道与运维脚本是全部库的唯一合法写入通道 |
| 下游只读 | 下游必须以 `mode=ro` 打开 SQLite；READ 层在文件系统层拒写（§7.2） |
| 数据根同源 | 读写两侧必须使用同一个 `EMSXVIEW_DATA_DIR`，否则读侧抛 `FileNotFoundError`（不创建空库） |
| WRITE 层禁破坏 | `DELETE` / `DROP` / `ALTER` 在 WRITE 层同样被拒绝（§7.2） |
| 公开 API | 外部只允许导入 6 个顶层符号（§1.4） |

### 1.3 与下游仓库（EMSXView）的交互

- 本仓库经 `010-extract-pipeline` 从上游业务仓库 EMSXView 抽出；EMSXView 现为下游只读消费方之一。
- 交互通道有两条：①**共享数据目录**——数据落 `<DATA_DIR>`（代码树之外，ADR-0016），下游以其只读访问层消费对应库/表；②**Runner HTTP**——本仓库 Runner（默认仅本机 `:8100`）提供管道触发与状态查询端点，下游后端以鉴权代理方式转发（前端不直连 Runner 端口）。
- 两仓**不互相 import 代码**。库/表/路径契约的真相源在本仓库 `DataPipeline/config.py`；下游仓库维护一份只读镜像并由契约测试锁定一致性，跨仓同步时优先修改本仓库。

### 1.4 公开 API 边界

外部消费者只应导入以下 6 个顶层符号（`DataPipeline/__init__.py`），**禁止** `from DataPipeline.storage.schema.columns import ...` 等内部路径（minor 升级会破坏）：

| 符号 | 角色 |
|---|---|
| `Config` | 全部路径、表名、格式、开关的单一事实源 |
| `ConnectionManager` | SQLite 连接生命周期、读写权限分层 |
| `AccessTier` | `READ` / `WRITE` 访问层级枚举 |
| `DatabaseFacade` | 仓库聚合入口（`fills_read/write`、`raw_fills_*`、`market_data_*`、`integrated_*`、`regime_*`） |
| `MarketStoreReader` | Parquet + DuckDB 批量读通道 |
| `MarketStoreWriter` | Parquet 批量写通道 |

CLI 入口：`python -m DataPipeline --once`（console script `emsx-pipeline`），最终调用 `orchestration.core.run_full_pipeline(...)`。

### 1.5 已知边界与退役组件（主动披露）

- **依赖本机 Bloomberg Terminal**（Windows）：`blpapi`/`xbbg` 需本机终端才能实际拉取；无终端环境仅能静态分析与跑 `pytest`。
- **默认 `--once` 只跑 S2→S3→S4→S6**；S5/S7/S8/S9/S10 属全量模式（§5、§9.3）。
- **已退役**：S1（Excel 摄入）永不执行；`processed_raw_bdib.db` 默认禁用（衍生列改内存即时计算，`PROCESSED_RAW_BDIB_ENABLED=1` 才启用）；历史一次性回填脚本已按 ADR-0014 清理（git 历史可恢复）。
- **诊断端点不是取数接口**：`/api/db/*/sample` 单次硬上限 200 行且只返回最新行（§9.2）。
- **平台限制**：仅 Windows 具备完整数据生产能力；macOS/Linux 可静态分析与测试。
- **空/未知交易所即报错**：S2 对空或未知 `Exchange` 直接抛 `ValueError`，不回退 NY 时区。

---

## 2. 总体架构

### 2.1 仓库布局

```
<REPO_ROOT>/
├── DataPipeline/        管道主包
│   ├── acquisition/     Bloomberg 采集（fills / BDIB / FX）
│   ├── ingestion/       拉取→落地→拉取审计（fill_fetch / fill_ingestion）
│   ├── processing/      清洗、增强、聚合、BDIB 整合、日指标、路由级 TCA
│   ├── analysis/        市场状态分类、成交归因、下游 manifest
│   ├── storage/         连接管理、门面、仓储、schema/迁移、Parquet/DuckDB
│   ├── validation/      护栏校验（Schema、契约、违规）
│   ├── pipeline_guards/ Schema 漂移静态扫描 + S5 前置数据质量守卫
│   ├── circuit_breaker/ 三态熔断、重试、告警
│   ├── monitoring/      运行级 JSONL 日志、RunID、概要
│   ├── orchestration/   阶段基类、Stage 集合、Context、Guard 包装
│   ├── maintenance/     参考数据集版本/时效同步
│   ├── common/          时区/映射/墓碑/配额暂停等共用工具
│   ├── config.py        ★ 配置单一事实源
│   ├── access_guide.py  ★ 取数通道阈值单一事实源
│   └── BUSINESS_FLOW.md 业务流程文档
├── runner/              常驻 FastAPI 服务（API + 只读诊断端点 + 前端静态托管）
├── frontend/            控制台 UI（Vite + React + TS，构建产物由 Runner 托管）
├── scripts/             运维 / 回填 / 归档脚本（ops/ 含启动编排）
├── tests/               跨库数据契约检查
└── docs/                数据库手册、数据访问指南、规格与 ADR
```

### 2.2 数据流转主图（10 库）

```
[Bloomberg EMSX GetFills] ──FillFetch(双层 hash 去重)──► raw_fills.db
        │  S2 清洗/增强 → S3 10s 聚合 → S4 订单标签
        ▼
processed_fills.db ──► execution_history.db / ticker_registry.db
        │  S5 整合 BDIB 行情 + FX → S5.5 路由级 TCA
[Bloomberg BDIB 10s bars] ──► raw_bdib.db (→ Parquet 可选双写) ──► fill_bdib.db
        │  S7 日指标 → S8 市场状态 → S9 成交打标 → S10 归因
        ▼
regime.db            （旁路产出：<DATA_DIR>/market_fetch_manifest.json）
```

10 个库文件（均位于 `<DATA_DIR>`；`processed_raw_bdib` 已退役默认禁用，活跃 9 个）：

| # | 库 | 关键表 | 写入方 | 读取方 |
|---|---|---|---|---|
| 1 | `raw_fills.db` | `raw_fills`、`fetch_log`、`order_fetch_log`、`ingestion_log`(legacy) | Fetcher | S2 |
| 2 | `processed_fills.db` | `processed_fills`、`route_registry`、`agg_fills_10s`、`processing_log` | S2/S3 | S3/S4/S5/S9 |
| 3 | `raw_bdib.db` | `raw_bdib`、`bdib_daily_summary` | S5/S7 | S5.5/S7/S10/下游 |
| 4 | `fill_bdib.db` | `fill_bdib`、`tca_route_summary`、`fx_rates`、`tca_report_dims(_meta)` | S5/S5.5/日更 | 下游消费方 |
| 5 | `regime.db` | `daily_{vol,liquidity,trend}_regime`、`fill_regime_labels`、`fill_attribution_metrics`、`daily_market_index`、`ref_*`、`audit_*` | S8/S9/S10 | 下游消费方 |
| 6 | `execution_history.db` | `route_registry`、`route_history`、`route_event_history`（`order_history` 为 VIEW） | S2 | 下游消费方 |
| 7 | `ticker_registry.db` | `ticker_repository`、`equ/ccy_ticker_registry`、`order_label`、`eur_composite_ticker_cache` | S2/S4 | S5/S6 |
| 8 | `fill_fetch_history.db` | `fill_fetch_history` | Fetcher | 审计 |
| 9 | `bdib_fetch_history.db` | `bdib_fetch_history` | S5 | 审计 |
| 10 | `processed_raw_bdib.db` | （退役，默认禁用） | — | — |

### 2.3 三种运行形态

| 形态 | 命令 | 阶段 | 说明 |
|---|---|---|---|
| 单次管道 | `emsx-pipeline --once` | S2→S3→S4→S6 | 默认 `skip_ingest=True`、`skip_bdib=True` |
| 常驻服务 | `.\start-data.ps1` | — | Runner API `:8100` + 前端 `:5183`；`POST /run` 子进程跑管道 |
| 日更调度 | `python scripts/daily_update.py` | 全量阶段链 | 每日 10:00 触发（schedule 库循环 + Windows 计划任务双形态），含拉取→全量阶段→manifest→归档→WAL checkpoint→维护同步→新鲜度 SLA→审计→报告钩子 |

---

## 3. 配置真相源（Config）

### 3.1 数据根解析

优先级：环境变量 `EMSXVIEW_DATA_DIR` > `Config.DEFAULT_DATA_DIR`（用户主目录下 `emsx_data` 占位目录，刻意不含机器路径；生产必须显式设置环境变量）。所有库/清单/墓碑/Parquet 路径常量均由 `DATA_DIR` 派生。

### 3.2 关键常量与开关（精选；完整清单见 `DataPipeline/config.py`）

| 类别 | 常量 | 默认值 | 说明 |
|---|---|---|---|
| 拉取范围 | `FIRST_RUN_LOOKBACK_DAYS` | 60 | 首跑回溯天数 |
| BDIB 白名单 | `BDIB_EXCHANGE` | 26 个交易所代码 | 拉取/分析范围白名单；2026-07-16 业务收缩至 25 个（保留 HK），2026-08-03 新增 `C1`（沪港通，行情代码映射 `CH`） |
| BDIB 时窗 | `BDIB_LATEST_READY_HOUR_LOCAL` | 8 | 当日 BDIB 安全就绪小时（本地时） |
| BDIB 保留窗 | `BDIB_API_RETENTION_DAYS` | 180 | Bloomberg 历史可拉窗口的保守取值（实测下界 ≥196 天；**影响不可逆决策**，注释含实测状态标注，勿凭印象改） |
| Parquet | `BDIB_PARQUET_ENABLED` | 0 | BDIB Parquet 双写开关（默认关，影响批量通道可用性 §7.5） |
| Parquet 目录 | `BDIB_PARQUET_DIR` | `<DATA_DIR>/market/bdib_10s` | Hive 分区布局 |
| 热留存 | `BDIB_HOT_RETENTION_MONTHS` | 3 | 热留存月数 |
| 查询引擎 | `BDIB_QUERY_ENGINE` | `duckdb` | 声明+导入期校验；**当前无代码消费点（未接线）** |
| 退役库 | `PROCESSED_RAW_BDIB_ENABLED` | 0 | 重新启用 `processed_raw_bdib.db` |
| 并发 | `MAX_PARALLEL_DATES` / `MAX_PARALLEL_TICKERS` | 1 / 1 | 防 OOM 的保守并发 |
| 护栏 | `GUARDRAIL_ENABLED` | 1 | 护栏总开关 |
| 护栏 | `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD` | 3 | 连续 ERROR 熔断阈值 |
| 护栏 | `GUARDRAIL_RETRY_MAX` | 3 | 外部拉取重试上限 |
| 护栏 | `GUARDRAIL_EMPTY_DATASET_POLICY` | reject | 空数据集策略 |
| 护栏 | `GUARDRAIL_VALIDATION_BYPASS_ON_ERROR` | 0 | 校验失败仅日志放行 |
| 严格度 | `STRICT_MISSING_TICKER_VALIDATION` | 0 | 缺 Ticker/Exchange 时是否硬报错 |
| S7 量纲守卫 | `GUARDRAIL_DAILY_VOLATILITY_MIN_MEDIAN_PCT` / `..._MIN_P90_PCT` / `..._MIN_SAMPLE` | 5.0 / 10.0 / 20 | 批次中位数<p5 且 p90<10 且样本≥20 才判「整批缺 ×100」拒绝入库 |
| BDIB 覆盖守卫 | `GUARDRAIL_BDIB_MIN_COVERAGE_RATIO` / `..._MAX_MISSING_MARKET_RATIO` / `..._MIN_MARKET_TICKERS` | 0.5 / 0.3 / 20 | 日期级市场完整性判据（§6.4） |
| 新鲜度 | `FRESHNESS_WARN_BUSINESS_DAYS` / `FRESHNESS_FAIL_BUSINESS_DAYS` | 1 / 2 | 按交易日计量；FAIL 升级日更失败（配额暂停期跳过） |
| FX/BBG | `BBG_COMPOSITE_QUERY_TIMEOUT_SEC` | 45 | EUR 复合 ticker 单 chunk 查询超时 |
| 维护 | `MAINTENANCE_MANIFEST_LOCK_TIMEOUT` | 10s | 维护清单跨进程锁超时（超时退化无锁继续） |
| 配额暂停 | `QUOTA_PAUSE_FILE` | `<DATA_DIR>/quota_pause.json` | 额度类故障的暂停标记（§8） |

### 3.3 导入期 fail-fast

`config.py` 末尾 `_validate_config()` 在**模块导入时**校验关键参数边界（查询引擎取值、阈值区间、空数据集策略等），非法值立即抛 `ValueError`，禁止静默降级。修改默认值必须先通过该校验。

> 常量注释约定（T23 事故后引入）：凡**影响不可逆决策**的常量（时间窗/保留期/清理阈值——取错会导致数据永久不可得），注释必须标注 `[实测状态] 已实测（依据+日期） | 名义假设（未实测）`。外部协作者引用这类常量时应先读其注释中的实测记录。

---

## 4. 数据获取（Acquisition & Ingestion）

本章给出三个数据源的接入方式、采集策略与去重/审计机制。代码主体在 `acquisition/` 与 `ingestion/`。

### 4.1 数据源 ①：Bloomberg EMSX 成交（GetFills）

**接入方式**：经 `blpapi` 直连 EMSX 服务。`BloombergFillFetcher._fetch_fills_once` 构造请求：`FromDateTime` / `ToDateTime`（格式 `%Y-%m-%dT%H:%M:%S.000+00:00`，单日全窗口 00:00:00–23:59:59）+ Scope 元素 `setChoice("TradingSystem")`。

**字段契约**：29 个 EMSX 提取字段（`OrderId` … `LocalExchangeSymbol`，含各字段 getter 类型，定义于 `acquisition/_constants.py::FILL_FIELD_EXTRACTORS`）；全宽 67 项期望列 `EXPECTED_FILL_COLUMNS`。`LimitPrice`/`StopPrice` 缺失/无效解析为 NULL（列类型 `REAL`）；`StrategyType` 为空属正常业务现象（部分 broker 本就不提供），后续统一归 `algo="other"`。

**会话与超时**：
- 事件超时 30s（`nextEvent(event_timeout_ms=30000)`，环境变量 `BLOOMBERG_TIMEOUT` 可覆盖）；
- 连续 3 次事件超时 → 抛错（判定 bbcomm 无响应，约 90s 无事件）；
- `fetch_fills` 默认 `max_retries=2`；超时类错误（关键词 `timeout`/`not responding`/`timed out`）→ disconnect → sleep 2s → reconnect；非超时错误按 `wait = attempt × 2` 秒指数退避；
- `ErrorResponse` / `ErrorInfo` 消息 → 提取 ErrorCode/ErrorMsg 抛 `EMSXRequestError`（不静默返回 0 行伪装成功）；命中额度 token 白名单（`QUOTA_EXCEEDED`/`RATE_LIMIT`/`MKT_LIMIT`/`MAX_MESSAGES`）→ 抛子类 `EMSXQuotaError`，不重试直接上抛。

### 4.2 数据源 ②：BDIB 10 秒行情

**接入方式**：经 `xbbg` 封装调用（统一经 `common/bloomberg_compat.py::import_blp()` 入口导入——为 blpapi 3.26 与 xbbg 0.10.3 的会话句柄不兼容注入兼容层，否则单次查询会新建 20+ 会话占满 control channel）。

**并行与分块**：`fetch_bdib_for_fills` 逐 `(ticker, date)` 提交线程池，`max_workers=4`；S5 上游再按每批 50 个 ticker 分块调用。

**安全日期三规则**（`bdib_fetcher`）：
1. `_is_trading_day`：拒绝未来日期与周六日（节假日集合当前为空常量，依赖 `permanent_gap_dates.json` 补充）；
2. `_is_safe_bdib_query_date`：目标日期 ≤ 上一工作日；且若「昨日为工作日但当前本地时间 < `BDIB_LATEST_READY_HOUR_LOCAL`(=8)」则再退一天（当日 bars 未就绪）；
3. 配额暂停置位时整体短路（§8）。

**数据形态**：原始 bar 10 列 `RAW_BDIB_COLUMNS`：`equ_ticker, order_as_of_date, mkt_timestamp, open, high, low, close, volume, num_trds, value`（`raw_bdib` 表另加审计列 `fetched_at`、`source`，共 12 列）。`mkt_timestamp` 由 bar 索引 floor 到 10s 区间起点，格式 `HH:MM:SS`（**不含日期**，完整时点须与 `order_as_of_date` 拼接）。

**失败处理**：抓取重试由 `RetryPolicy(max_retries=3, base_delay=1s, backoff_factor=2.0)` 统一处理，重试耗尽返回 None（该日该 ticker 缺项，不阻断其他 ticker）。异常消息含 `Cannot find exchange info` → 立即写入 `outdated_tickers.json` 墓碑（记录 first/last_seen_at、hit_count，原子写）且不重试；后续拉取直接跳过墓碑 ticker。

### 4.3 数据源 ③：FX 汇率

**接入方式**：`acquisition/fx_fetcher.py` 用 `blp.bdh` 拉 `USD{ccy} Curncy` 的 `PX_LAST`，换算 `fx_rate = 1.0 / raw_px`（语义：**1 单位本币兑美元数**）；USD 与空币种恒为 1.0。

**优先级与降级链**（`fetch_fx_rate_for_ccy`）：
1. `fx_rates` 表精确命中（币种 × 交易日，**零配额消耗**，先于额度暂停检查）；
2. miss 且未暂停 → 拉 Bloomberg；成功才落表（幂等 REPLACE，`px_last` 双存，`source='bloomberg'`）；
3. 拉取失败 / 配额暂停 / 空数据 → `_degraded_rate` 降级链：表内 ≤目标日期最近已知（带日期上界防未来泄漏）→ 内存缓存 → **1.0 兜底**（降级值只返回、**不落表**）。

批量入口 `fetch_fx_rates_for_date` 先单 SQL 批量查表，miss 币种才逐个拉取。

### 4.4 采集策略与去重/审计（FillFetch）

`ingestion/fill_fetch.py::FillFetch` 是成交采集的统一入口，`fetch_day` 单日流程：

```
拉取 → compute_data_hash → 双层去重 → validate_fill_data
     → upsert_raw_api_data（写 raw_fills）
     → add_fetch_log_record + upsert_order_fetch_log
     → fill_fetch_history.add_fetch_record（审计）
```

**日期范围策略**：`determine_fetch_range` 从「最早已 fetched 日期」扫到上一工作日（`weekday<5`），剔除 `permanent_gap_dates.json` 中已判定永久缺失的日期；`fetch_range_aggregated` 单会话逐日循环（周末跳过），直到今日缺口补齐。首跑回溯 `FIRST_RUN_LOOKBACK_DAYS=60` 天。

**双层 hash 去重**：
- 指纹 = `SHA-256(json.dumps(fills, sort_keys=True, default=str))`（日级批次指纹；BDIB 侧另有按 `(tickers, row_count)` 的轻量 hash）；
- 去重键 = `(source_date, data_hash)`；
- 第一层内存：`_known_hashes[date][hash]`（启动时从 `fetch_log` 预载，运行中回写）；第二层 DB：`check_fetch_duplicate` 查 `fetch_log`。

**fetch_log 软状态机**（`raw_fills.db.fetch_log.status`，CHECK 约束）：

| 状态 | 语义 | 翻转时机 |
|---|---|---|
| `fetched` | 该 `source_date` 当前有效批次 | 新批次写入时，旧行 UPDATE 为 `deprecated`，新行 INSERT `fetched`（latest-wins 同时保留审计） |
| `deprecated` | 被同日新批次取代 | 同上 |
| `failed` | 拉取失败（`data_hash` 记 `"failed:"+reason` 占位） | `record_fetch_failed`；不推翻既有 `fetched` |
| `superseded` | 保留状态值 | 仅 schema CHECK 允许，**当前无翻转代码** |

缺口扫描只认 `fetched`，因此 failed 日次日会被重试。`UNIQUE(source_date, data_hash)` 防止同指纹重复入库。

**配额暂停短路（quota_pause）**：`fetch_range_aggregated` 开头若 `quota_pause.json` 置位 → 用首个工作日做**真实探测**：成功则清除标记继续正常拉取；失败则保持置位并 `quota_shortcircuited=True` 跳过全部日期（`summary.success` 恒 False，不伪装成功）。空响应是否视为配额故障由 `_should_treat_empty_as_quota` 判定。标记文件由 `common/quota_pause.py` 原子写（临时文件 → replace）。

### 4.5 采集层异常处理汇总

| 现象 | 处理 |
|---|---|
| 3 次连续事件超时 | 抛错（bbcomm 无响应） |
| 超时类错误 | disconnect → 2s → reconnect，外层重试 ≤2 次 |
| 其他请求错误 | `attempt×2` 秒指数退避重试 |
| 额度类错误 | `EMSXQuotaError` 不重试；空响应变体判 `_should_treat_empty_as_quota` → 置位 `quota_pause.json` |
| `Cannot find exchange info` | 写 outdated 墓碑，永久跳过该 ticker |
| 解析异常 | `logger.warning`（非静默吞掉） |
| 失败日 | `fetch_log.status='failed'`，次日缺口扫描自动重试 |

---

## 5. 处理链路（S2–S10 逐阶段）

编排入口：`orchestration/core.py::PipelineFactory.create_daily_e2e_pipeline(skip_ingest, skip_bdib)` —— 恒注册 S2→S3→S4；`skip_bdib=False` 时追加 S5→S5.5→S7；恒以 S6 收尾；S1 仅在显式 `skip_ingest=False` 时注册（已弃用，打警告）。`run_full_pipeline` 默认 `GUARDRAIL_ENABLED=True`，经 `GuardPipeline` 包装执行（§6）。`PipelineContext` 持有 `target_dates`（缺省空列表 → 各 Stage 自行增量发现）、`force`、`config`、`summary`、错误收集器，db 连接懒初始化。

### 5.0 阶段总表

| Stage | 类 | 输入 | 输出/表 | 默认 --once |
|---|---|---|---|---|
| S1 Ingest Excel | `IngestExcelStage` | Excel | `raw_fills` | **废弃，永不执行** |
| S2 Process Raw Fills | `ProcessRawFillsStage` | `raw_fills` 当日 | `processed_fills`、`route_registry`、`route_history`、`route_event_history` | 是 |
| S3 Aggregate Fills 10s | `AggregateFillsStage` | `processed_fills` 单日 | `agg_fills_10s` | 是 |
| S4 Order Labels | `GenerateOrderLabelsStage` | `processed_fills` 单日 | `order_label`（ticker_registry.db） | 是 |
| S5 Integrate BDIB | `IntegrateBDIBStage` | `agg_fills_10s` + BDIB bars + FX | `raw_bdib`、`fill_bdib` | 否 |
| S5.5 Route Metrics | `ComputeRouteMetricsStage` | `fill_bdib` + `processed_fills` | `tca_route_summary` | 否 |
| S6 Write Manifest | `WriteManifestStage` | ticker registry | `market_fetch_manifest.json` | 是 |
| S7 Daily Metrics | `CalculateDailyMetricsStage` | `raw_bdib` + BBG bdh | `bdib_daily_summary` | 否 |
| S8 Regime Daily | `RegimeDailyFeaturesStage` | 指数/BDIB 聚合 | `daily_{vol,liquidity,trend}_regime` | 否 |
| S9 Fill Tagger | `RegimeFillTaggerStage` | `processed_fills` × regime | `fill_regime_labels` | 否 |
| S10 Attribution | `AttributionMetricsStage` | `processed_fills` + `raw_bdib` | `fill_attribution_metrics` | 否 |

### 5.1 S2：清洗与增强（核心阶段）

**清洗三步**（`processing/fill_cleaner.py::clean_emsx_fills`）：

1. **DFD 过滤**（`filter_out_dfd`）：`ExecType` strip+upper 后 `== 'DFD'`（Done For Day，订单当日完成、非成交事件）的行剔除，不入事实表。
2. **时区转换**（`derive_exchange_times`）：以 `America/New_York` 为基准，按订单所属交易所转为交易所本地时区（`common/exchange_tz.py::batch_convert_ny_to_local`：按 Exchange 分组 → 每组一次 ZoneInfo 查找 + pandas 向量化转换，10–50× 于逐行；**空/未知 Exchange 直接抛 `ValueError`，禁止回退 NY**；混合时区序列兜底转 UTC；返回 tz-naive 本地墙上时间）。输出 5 个派生列：`local_fill_datetime`、`order_as_of_date`(YYYYMMDD)、`exchange_exec_time`(HH:MM:SS)、`order_as_of_time`、`route_as_of_time`。解析格式回退列表 `Config.EMSX_DATETIME_FORMATS`（8 种）。
3. **字段标准化**（`normalize_fill_columns`）：修复 pandas 把字符串 `"NA"` 误解析为 NaN 的问题（荷兰阿姆斯特丹交易所代码 `NA` / 加拿大国民银行 ticker `NA`）——字符串 `"nan"` 还原为 `"NA"`，真 NaN 保持 NaN 不降级；写入入口 `upsert_raw_api_data` 另从原始 dict 反查二次兜底。

**增强五步**（`processing/fill_processor.py::process_fills`，尾部硬校验 `Exchange`/`equ_ticker` 非空）：

1. **algo 分类**（`add_algo_column`）：`Broker × StrategyType` 匹配 `common/mapping.py` 的 vwap/twap/pov/close 四组映射（如 EQ-HSBC `VWAP.`、EQ-CLSA `VWAP_ADP`）；未命中 → `other`。
2. **币种推导**（`add_currency_columns`）：`ccy_ticker = "USD"+ccy+" Curncy"`；USD → `USD Curncy`。
3. **equ_ticker 生成**（`add_equity_ticker`）：`(Ticker + " " + Exchange + " Equity").strip()`；KRW ticker 自动 `zfill(6)`；`C1`（沪港通）→ 代码映射 `CH`；空 Ticker/Exchange → NULL + ERROR（`STRICT_MISSING_TICKER_VALIDATION=1` 时直接抛错阻止入库）。**EUR 复合 ticker** 走缓存优先四步：① 读 `eur_composite_ticker_cache` 全量 → ② 拆命中/未命中 → ③ 未命中查 Bloomberg `EU_COMPOSITE_TICKER`（每 chunk 100 个、独立线程 + `BBG_COMPOSITE_QUERY_TIMEOUT_SEC=45s` 超时、配额暂停短路）并回写缓存 → ④ 仍未命中保留原始拼接值（fallback）+ warning。
4. **10 秒钟时间戳**（`add_mkt_timestamp_columns`）：`exchange_exec_time` 解析后 floor 到 10s。
5. **路由级时间戳**（`add_route_mkt_timestamp_columns`）：整秒取整。

**收盘竞价识别**：遍历 `closing_auction_times`（34 个交易所的收盘竞价时刻，如 US=16:00、JP=15:30、HK=16:00）；`EXCHANGE_AUCTION_TIME_ADJUST` 集合（JP/PW/SS/BZ/CN/MM/US）用「exec_time+1min ≥ close_time」判定（这些市场竞价时段提前开始），其余市场用 `mkt_timestamp ≥ close_time`。

**落库**（`ingestion/fill_ingestion.py::process_raw_fills_for_date`）：

- **日期一致性校验（写入前硬闸）**：处理后数据的 `order_as_of_date` ≠ 输入日期 → 抛 `ValueError` 整批拒绝，阻止跨日污染；
- 同事务写 `processed_fills`（PK `(OrderId, RouteId, FillId, order_as_of_date)`；`upsert` 的 key_columns 与 DDL 主键四元组对齐）；
- 写 `route_registry`（含 4 个 count 列：`count_fill=nunique(FillId)`、`count_broker`、`count_algo`、`count_trader`，按 `(OrderId, RouteId)` 分组预计算后 upsert）；
- 构建 `route_history` / `route_event_history`（保留 `equ_ticker`/`ccy_ticker`/`Side` 供下游高频 JOIN）并写 `execution_history.db`。

**时区语义三类（严禁混用）**：

| 类型 | 代表列 | 时区/格式 |
|---|---|---|
| 原始 NY | `DateTimeOfFill`、`NyOrderCreateAsOfDateTime` | ISO8601 含 tz 后缀 |
| 本地交易所 | `local_fill_datetime`、`mkt_timestamp`、`order_as_of_date`、`exchange_exec_time` 等 | 本地 tz，**无 tz 后缀**（ISO / `YYYYMMDD` / `HH:MM:SS`） |
| UTC | `source_refreshed_at` | ISO8601 含 `+00:00` |

**关键历史教训（写入语义设计依据）**：
- `source_date`（拉取日）≠ `order_as_of_date`（真实交易日）。S2 增量维度固定为 `raw_fills` 的 `DISTINCT order_as_of_date`（2026-07 跨日修复：此前按 `source_date` 处理曾致 13 个拉取日 / 360 万行因日期不一致被整批拒绝）。
- 间歇填充（gap filling）已移除（曾致 23GB 表膨胀）。

### 5.2 S3：10 秒桶聚合

`processing/fill_aggregator.py::generate_agg_fills_10s`：

- 聚合键：`groupby(["OrderId", "RouteId", "mkt_timestamp"])`；
- 类别列取 unique/multi、数值列（`FillShares`/`RouteShares`/`Amount`）求和；
- **VWAP 公式**：仅 `FillShares > 0` 的行贡献（`_exec_val = FillPrice × FillShares`），`VWAP = Σ_exec_val / Σ_FillShares`；桶内 Σshares ≤ 0 整桶丢弃（避免 `FillPrice` 出现单条 NULL）；
- **列补全**：`processed_fills` 对 `Ticker/Side/Currency/ccy_ticker` 去冗余，聚合前经 LEFT JOIN `route_registry` 补回四列（`Ticker` = `equ_ticker` 首段，`Currency` = `ccy_ticker` 去掉 ` Curncy` 后缀）；
- 增量键 `stage="aggregated"`；**失败日期也 mark_date_processed（row_count=0）**，防止坏日期死循环重试。

### 5.3 S4：订单级标签

`processing/order_label.py::generate_order_label_incremental`：逐日处理（避免 OOM），订单级标签集（side/amount/algo 等）累计向后传递；写入 `ticker_registry.db` 的 `order_label` 表；增量排除用该表 distinct 日期。

### 5.4 S5：BDIB 整合（TCA 衍生层）

`orchestration/stages_process.py::IntegrateBDIBStage`（全量模式）：

1. **候选日期只向前看**：从 `raw_bdib` 最新日期 +1 到 `latest_safe`（安全日期规则 §4.2）；
2. **前置守卫**：`EmptyBarGuard` + `BDIBCoverageGuard`（§6.4）；
3. **ticker 宇宙**：`Config.BDIB_EXCHANGE` 白名单过滤 `ticker_repository`；映射为空 → `summary.short_circuit_reason` 显式短路（不静默空跑）；
4. **Phase A/B 拉取**：BDIB bars 写 `raw_bdib`（+可选 Parquet 双写与 `processed_raw_bdib` 双写，后者默认退役）+ `bdib_fetch_history` 审计；
5. **FX Phase**：按币种批量取汇率（§4.3）；
6. **Phase C 整合**（`processing/fill_bdib_integrated.py::integrate_fills_bdib_for_date`，全内存）：
   - BDIB bars LEFT JOIN 10s 聚合成交（键 `(equ_ticker, mkt_timestamp[, order_as_of_date])`）；
   - FX 按 `(order_as_of_date, ccy_ticker)` join（`USD CURNCY` 规范为 fx_rate=1.0）；
   - 日频宽表 `daily_equity_data`（`chg_pct_1d`/`bid_ask_spread_%`）melt 后按 `(order_as_of_date, equ_ticker)` join——**当前 S5 调用未传入该参数，两列恒 NULL**（§11 优化点 P1-B）；
   - `FillShares/FillPrice` 更名 `fill_volume/fill_px`；`fill_volume ≤ 0` 行过滤；
   - `_compute_derived_metrics` 逐笔计算衍生指标（下表）后写 `fill_bdib`（PK `(OrderId, RouteId, order_as_of_date, mkt_timestamp)`）。

**fill_bdib 衍生列语义**（全部按 OrderId 内累计）：

| 列 | 定义 |
|---|---|
| `fill_value` | `fill_volume × fill_px` |
| `side_sign` | Sell → −1（方向化符号） |
| `cum_fill_value` / `cum_fill_volume` | 成交额/量累计 |
| `cum_market_volume` / `cum_market_value` | 市场 bar 量/额累计 |
| `participation_rate` | `cum_fill_volume / cum_market_volume × 100` |
| `vwap_slippage_bps` | `(fill_px − bar vwap)/bar vwap × 1e4 × side` |
| `arrival_slippage_bps` | `(fill_px − 订单首 bar vwap)/首 bar vwap × 1e4 × side` |
| `px_diff_bps` | fill vs bar 差价 bps（不带方向符号） |
| `cum_vwap` / `cum_fill_vwap` | 市场/成交累计 VWAP |
| `cum_slippage_bps` | `(cum_fill_vwap − cum_vwap)/cum_vwap × 1e4 × side` |
| `cum_slippage_usd` | `cum_slippage_bps / 1e4 × |cum_fill_value|` |
| `cum_volume_pct` | `cum_fill / cum_market × 100` |
| `cum_tracking_error` | `px_diff_bps` 的 expanding std |
| `cum_info_ratio` | `cum_slippage / cum_tracking_error` |
| `cum_interval_volatility` | `log_chg_pct_10s` 的 expanding std（按 `(equ_ticker, order_as_of_date)` 分组、组内按时间排序——T20 跨 ticker 污染修复后口径） |
| `standard_cum_interval_volatility` | 上者 ÷ 全局非零均值 |

### 5.5 S5.5：路由级 TCA 汇总

`processing/tca_route_metrics.py` 产出 `fill_bdib.db.tca_route_summary`（PK `(OrderId, RouteId, order_as_of_date)`，56 列 = 17 源值 + 18 计算 + 5 Phase0 基准 + 15 Phase1 风险/冲击 + `fx_rate`）。要点：

- **bar 切片语义**：`_slice_bars` 默认 `inclusive_end=True`（终点 `<=end`）；连续段参与率 `par_rate_continuous` 用 `False`（首笔竞价 fill 不计入）；全窗口终点取 `min(last_fill, last_bdib)`。bar 时间戳为区间起点，末 bar 覆盖 `[ts, 收盘竞价结束)`。
- **收盘窗口**：`_get_closing_auction_window` 按 `closing_auction_times` 确定；ADJUST 市场 start=close−1min；纯竞价路由窗口为空且 fill ≤ close+5min 时钳到末 bar。
- Phase0 基准：到达价/收盘价/机会成本（`TCA_CORE_BENCHMARKS_ENABLED`）；Phase1：Wagner IS 分解 + 风险维度 + 冲击分解（5/10/30min + 次日收盘，`TCA_RISK_IMPACT_ENABLED`）；PWP（参与率）档位 5%–25%、RPM 等。
- 增量排除 `tca_route_summary` 已有日期；先从 `fill_bdib` 回填 `fx_rate` 写回 `processed_fills` 再计算。

### 5.6 S6：Manifest（下游通知）

`analysis/downstream_interface.py::write_manifest` 写 `<DATA_DIR>/market_fetch_manifest.json`：

```json
{ "last_updated": ..., "new_tickers": [...], "updated_dates": [...],
  "equ_tickers": [...], "ccy_tickers": [...], "<equ/ccy 计数>": ...,
  "processed_fills_db": "<库文件名>" }
```

供下游 MarketFetch 监听增量信号（§10 交易前链路的「通知」环节）。

### 5.7 S7：行情日指标

`processing/daily_metrics_calculator.py::CalculateDailyMetrics.run_for_date`：

- Bloomberg 字段：`PX_VOLUME`、`VOLATILITY_30D`、`PX_LAST`（60 日历天回看，每 chunk 50 ticker；chunk 失败退化为逐 ticker 重试；配额暂停短路）；
- 计算：`adv_5d`/`adv_20d` = 末 5/20 个交易日量均值（len≥2 才算）；`daily_vwap = Σ(close×vol)/Σvol`；`intraday_volatility` = 10s 对数收益 std × √(252×6.5×3600/10) 年化（**小数**）；`daily_volatility` 直取 `VOLATILITY_30D`（**年化百分比**，26.0 = 26%）；
- 增量：`SELECT DISTINCT trade_date FROM bdib_daily_summary` 排除已算日期；
- **量纲守卫** `_volatility_scale_ok`：批次样本 ≥20 且 `daily_volatility` 中位数 < 5.0 **且** p90 < 10.0 → 判「整批被写成小数（缺 ×100）」拒绝入库；仅中位数低而 p90 正常 → 真实低波动横截面，WARNING 放行（防长尾误伤）。

### 5.8 S8：市场状态分类（regime）

三个日级分类器（配置版本化，落表 PK `(market_code, trade_date, config_version)` UPSERT，配置版本记 `audit_regime_config_versions`）：

| 维度 | 主判据 | 降级判据 |
|---|---|---|
| 波动率 vol | VIX 绝对阈值 low<12 / normal<18 / high<25（分类边界） | VIX 全 NULL → realized_vol_zscore（60d rolling，min_periods=10，边界 −1/1/2；降级时回看 90 天） |
| 流动性 liquidity | 换手率 z-score：thin < −1 / thick > +1（lookback 60d） | — |
| 趋势 trend | `dist_52w_high = (px − high_252d)/high_252d`；uptrend：dist ≥ −0.10 且 px > MA50 > MA200；downtrend：RSI30 < 35 且 px < MA50 < MA200；否则 range | — |

### 5.9 S9：逐笔成交市场状态打标

`analysis/regime/fill_regime_tagger.py::tag_fills`：取区间 `processed_fills` → `derive_market_code`（交易所码折叠：EUR 一律归 `EU`；`MUMBAI/BOMBAY/INDIA/NSE/BSE → IN`；无 Currency 时 11 个欧洲交易所折叠）→ 关联三种日级 regime → 查 `ref_macro_event_calendar` 标记宏观事件窗 → `assign_time_bucket` 打日内时段标签（仅 5 个启用市场 US/AU/LN/EU/JP，各 5 桶 open_30m/morning/midday/afternoon/close_30m，JP 额外 lunch_break 11:30–12:30，桶 end 独占；其余市场 time_bucket 为 NULL）→ UPSERT `fill_regime_labels`。

### 5.10 S10：执行归因

`analysis/attribution/`：拉 1min bar panel → 计算：

- `is_bps = side × (fill_px/arrival_px − 1) × 1e4`（IS 滑点，正 = 对 taker 不利）；
- `vwap_bps` 同型（对 interval VWAP）；
- `reversal_{1m,5m,30m}_bps = side × (mid_at_fill+N − fill_px)/fill_px × 1e4`（价格反转）；
- `pct_adv = fill_shares / bdib_daily_summary.adv_20d`；
- `participation_rate = RouteShares / 区间 bar 量`（>5 视为异常置 NULL）。

结果 UPSERT `regime.db.fill_attribution_metrics`；成功后对结果集计算 SHA-256 写 `research_snapshot` 表（研究快照，可复现审计）。另有 S11 层聚合（cell = `(broker, algo[, regime])` × 指标 `is_bps/vwap_bps/reversal_{1m,5m,30m}_bps`，`pct_adv` 分桶 [0, 0.5%, 1%, 5%, 100%]，bootstrap 95% CI + Welch t + BH-FDR 校正）——**聚合只算不落库**（内存返回给调用方）。

---

## 6. 校验与护栏（Guardrail 子系统）

### 6.1 GuardPipeline 包装模型

`orchestration/guard.py` 的 `GuardPipeline` **不侵入** `FinancialPipeline`，按阶段注入：

```
每个阶段：跳过判定 → 熔断器 OPEN? → 阻断
        → before_stage（输入预检）
        → stage.execute()
        → Validator.validate_output（输出校验）
        → record_success/failure（熔断计数）
        → JSONL 日志（STAGE_START/END/VIOLATION/CIRCUIT_BREAK）
异常时回退到原生 pipe.run()（护栏自身故障不拖垮业务管道）。
```

S0 预检：`SchemaDriftGuard` 在管道启动前静态扫描 DDL 与代码写入路径的 schema 漂移（4 类检测：PRIMARY_KEY_TYPE_MISMATCH / COLUMN_MISSING_IN_DDL / COLUMN_MISSING_IN_CODE / VALUE_TYPE_MISMATCH；白名单项降级 INFO，未知漂移 ERROR 阻断；只告警不自动修复）。

### 6.2 组件矩阵

| 组件 | 位置 | 能力 |
|---|---|---|
| `Validator` | `validation/validator.py` | Pydantic `model_validate` 逐条校验；STRICT/RELAXED 策略；错误映射到 ViolationType/SeverityLevel；空数据集策略 |
| `SchemaRegistry` | `validation/schema_registry.py` | 各 Stage INPUT/OUTPUT 模型注册；`check_contract` 静态契约检查 |
| `ContractChecker` | `validation/contract_checker.py` | 字段存在性/类型兼容/必填三检 → COMPATIBLE/WITH_WARNING/INCOMPATIBLE |
| `CircuitBreaker` | `circuit_breaker/breaker.py` | CLOSED→OPEN→HALF_OPEN；按 `run_id`+`stage` 隔离；CRITICAL 立即 OPEN |
| `CircuitBreakerRegistry` | `circuit_breaker/breaker_registry.py` | `get_or_create`/`cleanup(run_id)`/`any_open` 聚合 |
| `SchemaDriftGuard` | `pipeline_guards/schema_drift_guard.py` | 启动前 schema 漂移静态扫描 |
| `EmptyBarGuard` / `BDIBCoverageGuard` | `pipeline_guards/` | S5 前置数据质量守卫（§6.4） |
| `RetryPolicy` | `circuit_breaker/retry_policy.py` | 指数退避（max_retries/base_delay/backoff_factor） |
| `PipelineRunLogger` | `monitoring/run_logger.py` | 内存缓冲 flush 到 `<LOG_DIR>/pipeline/guardrail/{run_id}.jsonl`（RUN_START/STAGE_*/VIOLATION/EXCEPTION/CIRCUIT_BREAK/RUN_END） |
| `Alert` | `circuit_breaker/alert.py` | 结构化日志告警 + 邮件/Webhook 扩展点 |

### 6.3 校验策略矩阵与熔断规则

| 阶段类型 | 策略 | 失败时 |
|---|---|---|
| Fetcher（外部 Bloomberg 拉取） | RELAXED（仅类型） | 告警放行 |
| S2–S10（内部计算） | STRICT | ERROR 累计达阈值熔断；CRITICAL 立即熔断 |

熔断：连续 `GUARDRAIL_CIRCUIT_BREAKER_THRESHOLD`（默认 3）次 ERROR 或任意 CRITICAL → 阶段返回 `CIRCUIT_BROKEN`，**后续阶段不再执行**，整管道置 `CIRCUIT_BROKEN`，发 critical 告警。恢复：手动 `breaker.reset()` → HALF_OPEN → 下次探测成功回 CLOSED；HALF_OPEN 期间任何非 INFO 失败立即回 OPEN。运行结束 `cleanup(run_id)` 释放。

### 6.4 数据级守卫（业务规则层）

| 守卫 | 判据 | 动作 |
|---|---|---|
| S2 日期一致性 | 处理结果 `order_as_of_date` ≠ 输入日期 | 抛 `ValueError` 整批拒绝入库 |
| S2 Exchange 空值/未知 | 映射表无该代码 | `ValueError`（不回退 NY） |
| S7 量纲守卫 | §5.7 三条件 | 拒绝该批次入库（防 100 倍量纲事故复发） |
| BDIB 覆盖守卫（日期级） | 「显著市场（ticker≥20）的完全缺失占比 > 0.3」或「ticker 覆盖率 < 0.5」 | 告警不阻断（已落库数据本身有效）——针对「库存级差集检查发现不了的市场级整块缺口」 |
| EmptyBarGuard | 空 bar 批次 | S5 前置拦截 |
| fresh­ness SLA | 核心库最新交易日落后 >1 交易日 WARN；>2 FAIL | FAIL 升级日更失败（配额暂停期豁免） |

### 6.5 降级开关

`GUARDRAIL_ENABLED=false` 全关（Stage 仍执行，无校验/熔断/JSONL）；`GUARDRAIL_VALIDATION_BYPASS_ON_ERROR=true` 校验失败仅日志不计熔断；`GUARDRAIL_EMPTY_DATASET_POLICY=accept` 空数据放行（默认 reject）。

---

## 7. 存储层

### 7.1 连接管理与访问分层（`storage/connection.py`）

`ConnectionManager` 集中管理全部库连接，按 `AccessTier` 分层：

| 层 | SQL 白名单 | SQL 拒绝 | 连接形态 |
|---|---|---|---|
| READ | 读类语句 | 一切非读（含 CREATE、写类 PRAGMA） | URI `file:...?mode=ro`；线程内按 `(database, row_factory)` 缓存 + `SELECT 1` 探活；**库文件缺失抛 `FileNotFoundError`（不创建空库）** |
| WRITE | `INSERT/UPDATE/REPLACE/UPSERT` | **`DELETE/DROP/ALTER`**（destructive 正则） | 每次新建；`journal_mode=WAL` + `foreign_keys=ON` + `busy_timeout=30s` |

所有连接由 `AccessControlledConnection` 包装，`execute()` 时按 SQL 正则做权限校验。DDL 唯一通道是 `execute_ddl`（仅允许 `ALTER TABLE` / `CREATE TABLE|INDEX|VIEW`）。

### 7.2 Schema 管理与迁移链

- 版本记录在每库 `PRAGMA user_version`；期望值 `EXPECTED_VERSIONS = {raw_fills: 5, processed_fills: 1, raw_bdib: 2, processed_raw_bdib: 1, fill_bdib: 1, regime: 3}`。
- 显式迁移链（forward-only，`storage/schema/migrations/`）：regime 主链 `v0→v3` + 子目录 `raw_fills/`（v0→v5）、`raw_bdib/`、`fill_bdib/`、`processed_fills/`、`processed_raw_bdib/`。`MigrationRunner` 校验 vN→vN+1 连续性，逐文件 `executescript` 并推进 user_version，原子性靠 SQL 文件内 `BEGIN/COMMIT` + admin 连接。
- 其余库走 `inline_ddl`（首次启动幂等建表/自动迁移，如 raw_fills 列类型升级 CREATE NEW + COPY + DROP + RENAME 单事务模式）。

### 7.3 关键表结构与索引（下游高频消费对象）

| 表 | 列规模 | 主键 | 索引/注意 |
|---|---|---|---|
| `raw_bdib` | 12 列 | `(equ_ticker, order_as_of_date, mkt_timestamp)` | 辅助索引 `idx_raw_bdib_date_ticker(order_as_of_date, equ_ticker)`；DDL 目标形态（历史线上库曾为两个单列索引，不影响按 ticker 查询——走 PK 首列）；**查询必须带前导列，否则 3.7 亿行/80GB 级全表扫描** |
| `fill_bdib` | 26 列 | `(OrderId, RouteId, order_as_of_date, mkt_timestamp)` | 含 `vwap`、`log_chg_pct_10s` 等衍生列 |
| `tca_route_summary` | 56 列 | `(OrderId, RouteId, order_as_of_date)` | `idx_trs_date` / `idx_trs_ticker`；**聚合分析优先走本表，勿扫明细** |
| `bdib_daily_summary` | 日级百万行 | — | **不落 Parquet**；`daily_volatility` 百分比 / `intraday_volatility` 小数 |
| `raw_fills` | 67 列 | `(OrderId, RouteId, FillId, source_date)` | `order_as_of_date` NOT NULL（v4 约束）；原始落地区不做派生 |

### 7.4 Parquet/DuckDB 批量通道（`storage/market_store.py`）

- 布局：`<DATA_DIR>/market/bdib_10s/year=YYYY/month=MM/data_YYYYMMDD.parquet`（snappy，Hive 分区）；同日重复写入先读旧文件 concat，再按 `(equ_ticker, order_as_of_date, mkt_timestamp)` 去重 keep last。
- 查询：DuckDB 建 VIEW `bdib_bars`（`read_parquet(glob, hive_partitioning=true)`）；`query()` 失败写 `last_query_error`（调用方必须检查，区分「真无数据」与「查询失败」）。
- `BDIB_QUERY_ENGINE`（默认 duckdb）当前为「声明 + 导入期校验但无代码消费点」的开关（§11 优化点 P2-A）。
- 可用性探测：`access_guide.probe_parquet_channel()` 返回 `{enabled, dir, partitions, file_count, rows, available, reason}`；`available=False` 时下游必须降级，不得静默返回空结果。

### 7.5 备份 / 归档 / 审计

时间戳 `.bak` 备份（`storage/backup.py`）；长期冷存归档（`storage/archiver.py`）；跨库审计表 `audit_pipeline_runs`（每次 stage 运行）与 `audit_research_snapshots`（SHA-256 快照）支撑复现。

---

## 8. 异常处理与降级总表（跨层汇总）

| 场景 | 触发条件 | 行为 | 可感知方式 |
|---|---|---|---|
| 配额爆满 | 额度类错误 / 预期有数据但拉空 | `quota_pause.json` 置位 → 各拉取入口（fills/BDIB/FX/日指标/维护）短路让路；下轮开头真实探测成功才清标记 | `summary.quota_shortcircuited`；日志标记 |
| FX 缺失 | `fx_rates` miss 且 BBG 拉取失败 | 降级链 → 1.0 兜底（**静默影响数据可信度**，降级值不落表） | 排查 `<LOG_DIR>`；对照 `fx_rates.source` |
| BBG 会话挂起 | 单 chunk 无响应 | 独立线程 + 超时（45s）跳过该 chunk | 日志 warning |
| ticker 无行情 | `Cannot find exchange info` | 墓碑永久跳过 | `outdated_tickers.json` |
| BDIB 拉取失败 | 重试 3 次耗尽 | 返回 None，该 ticker-date 缺项不阻断 | `bdib_fetch_history` |
| 阶段业务异常 | Stage 内抛错 | `BaseStage.execute` 顶层捕获 → `context.log_error` → 管道中断（返回 False） | summary + JSONL |
| 校验失败累积 | 连续 ≥3 ERROR 或 1 CRITICAL | 熔断，后续阶段全部跳过 | JSONL CIRCUIT_BREAK + 告警 |
| schema 漂移 | DDL vs 代码不一致 | 启动前 ERROR 阻断（白名单除外） | SchemaDriftGuard 报告 |
| 维护同步失败 | 同步异常/超时 | 只写 `summary["maintenance"]`，不参与 failed 判定、不阻断启动 | `/maintenance/status` |
| 数据新鲜度 | 落后 >2 交易日（非配额暂停期） | 日更终态 failed + exit 1 | daily_update 状态 |
| 长任务无输出 | BDIB 等长 Stage | 每 date/批次打 `[STAGE] {name} {pct}` 进度行（Runner 解析为 progress） | `/status.progress` |
| 内存峰值 | 数百 ticker × 数月 BDIB | 各 Stage 循环体内 `del` + `gc.collect()`；并发上限保守（=1） | — |

---

## 9. 运行时服务与编排

### 9.1 CLI

- `python -m DataPipeline --once [--skip-bdib] [--skip-ingest]`（两个 skip **默认 True**）。
- `python -m DataPipeline.maintenance [--force] [--key]`：手动维护同步。

### 9.2 常驻 Runner（`runner/app.py`，console script `emsx-runner`）

| 端点 | 说明 |
|---|---|
| `POST /run` | 触发管道（`include_fetch=1` 时改跑日更脚本）；运行中重复触发返回 **409**（幂等） |
| `GET /status` | `id/state(idle|running|success|failed)/started_at/finished_at/duration_sec/returncode/log_tail(50 行)/log_path/progress/stage/stage_detail/last_activity_at/completed_stages/total_stages` |
| `GET /health` | 健康检查 |
| `GET /maintenance/status`、`POST /maintenance/sync` | 维护同步状态 / 手动触发（409 幂等） |
| `GET /api/db/overview`、`/api/db/{key}/summary?date_limit≤3650`、`/integrity`、`/tables/{t}/schema`、`/tables/{t}/sample?limit∈[1,200]`、`/api/db/access-guide` | 只读诊断（**不是取数接口**）：库/表白名单校验、`mode=ro`、路径遮蔽为文件名 |
| 静态托管 | `mount("/", StaticFiles(frontend/dist, html=True))` **必须置于所有 API 路由注册之后**（否则遮蔽 API，历史事故） |

实现要点：`POST /run` 子进程隔离执行 `python -u -m DataPipeline --once`（或日更脚本），**无显式超时**——逐行读 stdout 到进程结束，日志 tail 保留 200 行并落盘 `pipeline-{id}.log`；心跳线程 2s 采样区分「慢」与「卡死」；进度优先解析 `[STAGE]` 标记行。CORS 白名单仅本机 `:5183`（`127.0.0.1` 与 `localhost` 两个 host 变体）；服务绑定 `127.0.0.1:8100`。

### 9.3 日更编排（`scripts/daily_update.py`）

调度：`--time` 默认 `10:00`，`schedule.every().day.at()` 循环；另有 `scripts/install_scheduler.py` 注册 Windows 计划任务（历史任务名保留）。三处默认时间必须一致（启动脚本/调度器/修复脚本）。

`run_daily_pipeline` 步骤顺序（严格）：

```
Stage A  fill_fetch（成交拉取；失败显式 ERROR → 终态 failed）
Stage B  run_incremental（skip_bdib=False，全量阶段链 S2..S10）
         write_manifest → 归档 → B4 观察
→ _checkpoint_wal（各库 PRAGMA wal_checkpoint(TRUNCATE)；
   processed_fills.db ≥10GB 阈值条件 VACUUM）
→ maintenance sync（必须在 WAL checkpoint 之后——维护适配器以 mode=ro 只读连接
   探测版本，先同步会看不到新数据；异常只记 summary，不参与 failed 判定）
→ freshness SLA（WARN>1 / FAIL>2 交易日；配额暂停期豁免 FAIL）
→ 交易所白名单审计 / 跨库守恒检查
→ report_dims 刷新（报告筛选维度持久化，查询不再对明细 GROUP BY）
→ TCA 报告（PIPELINE_REPORT_CMD 外部钩子）
→ 终态：fetch|stage|freshness 任一失败 → status=failed → exit 1
```

### 9.4 启动编排与自愈（`scripts/ops/`）

- `bootstrap.ps1` 是**唯一启动入口**：单实例锁 → preflight（环境预检）→ 自愈 → Runner/前端/调度器差异化健康门 → 退出码 `0`(成功)/`10`/`11`/`12`；日志统一落 `<LOG_DIR>/bootstrap/`（文本 + JSONL）。
- `repair.ps1`（L1 重启 → L2 依赖/数据目录 → L3 安全回滚）+ `retry.ps1`（退避/熔断/每日预算）。
- `install-autostart.ps1` 安装开机自启动（任务计划，受限时自动降级启动文件夹）；`-Status` 查看形态与健康。
- 纪律：所有含中文的 `.ps1` 必须存为 UTF-8 with BOM（PowerShell 5.1 兼容，安装器注册前自检）。

### 9.5 维护数据同步（`DataPipeline/maintenance/`）

**7 个参考数据集**（registry 定义，各自同步策略）：

| 数据集 | 策略 | 备注 |
|---|---|---|
| `ticker_repository` | self_heal | |
| `equ_ccy_ticker_registry` | self_heal | 从 `processed_fills` 全量重算 |
| `route_registry` | local_only | 存 `execution_history.db` |
| `fx_rates` | local_only | §4.3 |
| `macro_event_calendar` | versioned | Bloomberg 30 天回看 |
| `outdated_tickers` | local_only | SLA 3650 天 |
| `exchange_whitelist` | local_only | **blocking=True**（失败可选阻断启动；默认降级不阻断） |

**清单**：`<DATA_DIR>/maintenance/manifest.json`，结构 `{schema_version, updated_at, datasets: {key: {local_version, remote_version, content_hash, last_checked_at, last_success_at, status, staleness_days, last_error}}}`。版本语义为**双轨**：`as_of` 游标（YYYYMMDD）+ 内容 hash（sha256 前 16 位）——因 Bloomberg 无版本号概念。快照目录保留 3 份供回退。

**跨进程排他锁**：Runner 与 daily_update 是两个进程，共享清单的读-改-写必须持锁。实现为锁文件首字节加锁（Windows `msvcrt.locking` / POSIX `fcntl.flock`），超时（默认 10s）退化为无锁继续（维护同步不得阻断主流程）。三重防失效：① 读路径靠 `os.replace` 原子性不加锁；② 持锁期间锁文件在 Windows 上无法被删除（`os.open` 不授予 `FILE_SHARE_DELETE`）；③ 加锁后按 `(st_dev, st_ino)` 自证锁文件未被替换。

**触发入口（三处）**：① Runner 启动 lifespan 后台线程；② `POST /maintenance/sync`（409 幂等）；③ 日更收尾（WAL checkpoint 之后）。另有 CLI 形态。

---

## 10. 交易前功能：业务逻辑与执行链路

### 10.1 定义与范围

本仓库**不执行任何交易**，也**不存在独立的「交易前市场快照产品」表**。所谓交易前功能，在本系统中指：**为交易前决策提供市场上下文（market context）数据的完整供给链路**——即「行情采集 → 日级指标 → 通知 → 下游只读消费」。下游的交易前消费方是上游业务仓库的 MarketView（交易前市场上下文看板，经市场参考数据适配器读 BDIB/日级特征）与 TCA 报告前端。

### 10.2 执行链路（端到端）

```
① 采集   S5 Phase A/B：BDIB 10s bars（安全日期规则 + 线程池 + 墓碑 + RetryPolicy）
              │  写 raw_bdib（12 列）＋ 可选 Parquet 双写（BDIB_PARQUET_ENABLED）
              ▼
② 指标   S7：bdib_daily_summary（ADV 5d/20d、daily_vwap、双口径波动率、量纲守卫）
         S8：daily_{vol,liquidity,trend}_regime（交易前市场状态判断依据）
              ▼
③ 通知   S6：market_fetch_manifest.json（新 ticker / 更新日期 / 全量 ticker 清单）
              —— 下游 MarketFetch 监听此文件获知「哪些数据可取」
              ▼
④ 消费   下游经两条只读通道取数：
         a) Python 门面：DatabaseFacade（mode=ro 点查，量级小）
         b) 批量通道：MarketStoreReader（Parquet+DuckDB，仅 raw_bdib，需先 probe 可用性）
         c) 诊断/自助发现：GET /api/db/access-guide（运行时通道决策矩阵）
              ▼
⑤ 报告   TCA 报告由日更收尾的外部钩子（PIPELINE_REPORT_CMD）生成；
         聚合分析优先读 tca_route_summary（56 列预计算表，勿扫明细）
```

### 10.3 各环节数据契约（交易前消费方必须知道的事实）

| 项 | 契约 |
|---|---|
| 时间戳 | `mkt_timestamp` 仅 `HH:MM:SS`（本地交易所时区、无 tz 后缀、非 UTC）；完整时点须与 `order_as_of_date`（YYYYMMDD）拼接 |
| ticker | `equ_ticker` 为 Bloomberg 复合代码（如 `000100 KS Equity`），**不是裸 ticker**；拼错不报错、只返回空结果 |
| 量纲 | `daily_volatility` 百分比（26.0 = 26%）；`intraday_volatility` 小数（0.35 = 35%）——跨列运算前先对齐 |
| 查询 | `raw_bdib` 查询必须带前导列（`equ_ticker` 或 `order_as_of_date`），否则全表扫描 |
| 脏数据 | Bloomberg 偶发 `close IS NULL`，消费方需自行过滤 |
| 衍生列 | `raw_bdib` 无 `vwap`/`log_chg_pct_10s`；需要时用内存计算或改读 `fill_bdib` |
| 新鲜度 | 日更 10:00 后更新；freshness SLA WARN 1 / FAIL 2 交易日；通道可用性以 `access-guide` 运行时探测为准 |
| 退役 | `processed_raw_bdib.db` 勿依赖 |

### 10.4 功能入口汇总（模块 × 入口）

| 功能 | 模块 | 入口 |
|---|---|---|
| 行情采集 | `acquisition/bdib_fetcher.py` | `fetch_bdib_for_fills`（S5 内部调用） |
| 行情落库 + 审计 | `storage/repositories/market_data.py` + `orchestration/stages_process.py` | S5 Phase A/B |
| Parquet 双写 | `storage/market_store.py::MarketStoreWriter` | S5（受 `BDIB_PARQUET_ENABLED`） |
| 日级指标 | `processing/daily_metrics_calculator.py` | S7 `run_for_date` |
| 市场状态 | `analysis/regime/{vol,liquidity,trend}_regime.py` | S8 三 classify |
| 通知 | `analysis/downstream_interface.py` | S6 `write_manifest` |
| 批量读 | `storage/market_store.py::MarketStoreReader` | 下游直接 import |
| 通道自助发现 | `access_guide.py` + `runner/db_routes.py` | `GET /api/db/access-guide` |

---

## 11. 交易前功能优化路径（可落地）

### 11.1 现状短板清单

| # | 短板 | 证据 |
|---|---|---|
| S1 | Parquet 批量通道默认关闭，下游大批量交易前取数不可用，被迫走 SQLite 分块扫描 | `BDIB_PARQUET_ENABLED` 默认 0；`probe_parquet_channel` 如实报 `available=False` |
| S2 | `fill_bdib` 的日频市场快照维度（`chg_pct_1d`、`bid_ask_spread_%`）链路已建但**未接线**，恒为 NULL | `fill_bdib_integrated.py` 支持该参数，S5 调用未传 |
| S3 | `BDIB_QUERY_ENGINE` 开关声明+校验但无消费点，属「幽灵开关」 | 全仓无代码读取该值做分支 |
| S4 | 采集并发保守（dates/tickers 均 =1），BDIB 全量回补吞吐受限 | `MAX_PARALLEL_DATES/TICKERS=1`（防 OOM 取值） |
| S5 | 节假日判据为空常量，仅靠周末过滤 + `permanent_gap_dates` 人工登记 | `_is_trading_day` 的节假日集合为空 |
| S6 | 交易前消费方缺少「一张表看全市场当日快照」的聚合视图（需自行扫 raw_bdib） | 无预计算快照表 |

### 11.2 优化项（按优先级；每项含模块/入口/步骤/风险/验证）

**P1-A：启用 Parquet 双写，打开批量通道**
- 模块/入口：配置开关 `BDIB_PARQUET_ENABLED=1`；写路径 `MarketStoreWriter`（S5）；读路径 `MarketStoreReader` + `probe_parquet_channel`。
- 步骤：① 预估磁盘增量（按 2,000 行/ticker·日 × 存量 ticker 规模）；② 灰度开双写跑 S5 若干交易日；③ `probe_parquet_channel` 确认 `available=True` 且行数与 SQLite 对账一致；④ 通知下游切换通道。
- 风险：磁盘占用与双写耗时；同日重写去重逻辑已内建（keep last）。
- 验证：`file_count`/`rows` 与 `raw_bdib` 按日 COUNT 对账；DuckDB 与 SQLite 抽样比对。

**P1-B：补齐交易前市场快照维度（接线 daily_equity_data）**
- 模块/入口：`orchestration/stages_process.py`（S5 Phase C 调用点）传参 `daily_equity_data`；数据源可复用 S7 已拉的 `PX_LAST`/`VOLATILITY_30D` 或扩展 `blp.bdp` 字段（前收、买卖价）。
- 步骤：① 构造日级宽表（`order_as_of_date, equ_ticker, chg_pct_1d, bid_ask_spread_%`）；② 传入 `integrate_fills_bdib_for_date`；③ 对存量日期用回填脚本补；④ 下游文档同步两列语义。
- 风险：新增 BBG 字段消耗配额（注意配额暂停联动）。
- 验证：抽样新写日期两列非 NULL 率；与 Bloomberg 终端抽查比对。

**P1-C：预计算「全市场当日快照」表（交易前聚合视图）**
- 模块/入口：新表落 `raw_bdib.db`（如 `bdib_market_snapshot`），生产入口建议挂在 S7 后（日更 Stage B 内），读侧走 `facade.market_data_read`。
- 步骤：① 定义快照列（每 ticker：首末 bar 时间、当日 OHLC/VWAP、量额、缺口、与 ADV 比）；② S7 末尾增量写；③ DATA_ACCESS.md 表级建议补行；④ 下游 MarketView 由扫明细改读快照。
- 风险：需新增 schema（走 inline DDL + 迁移链规范，user_version+1）。
- 验证：与 raw_bdib 明细聚合对账（抽样 ticker×date）。

**P2-A：`BDIB_QUERY_ENGINE` 接线或移除**
- 二选一：① 让 `market_store` 读路径真正按引擎分流（当前仅 DuckDB 一条实现，接线意义有限）；② 移除开关与校验（降低误导）。建议后者，待 Parquet 通道稳定后再评估多引擎。
- 风险：移除属公开配置语义变化，需按 §13 触发文档更新并通知下游。

**P2-B：采集吞吐逐级放大**
- 模块/入口：`MAX_PARALLEL_DATES` / `MAX_PARALLEL_TICKERS`（S5 提交线程池）。
- 步骤：在 Bloomberg 配额与内存余量内按 1→2→4 灰度；配合现有 `[STAGE]` 进度与 JSONL 观测；配额暂停机制已在位（超限自动短路）。
- 风险：内存峰值与配额消耗（daily metrics 的 60 天回看会放大请求量）。

**P2-C：索引形态收敛确认**
- `raw_bdib` 历史线上库为两个单列索引，DDL 已计划合并为 `idx_raw_bdib_date_ticker(order_as_of_date, equ_ticker)`；执行后用 `EXPLAIN QUERY PLAN` 验证高频查询形态不变（按 ticker 查走 PK 首列）。

**P3：交易日历增强**
- 为 `_is_trading_day` 接入真实节假日日历（可与 `macro_event_calendar` 同源维护），减少无效配额探测与 `permanent_gap_dates` 人工登记。

### 11.3 建议实施顺序

P1-A（零代码、立刻可做）→ P1-B（小改 S5 传参）→ P1-C（新表，走 schema 规范）→ P2（P2-C 随任意维护窗口；P2-A 择机）→ P3。每项完成后按 §13 触发文档更新。

---

## 12. 下游取数速查（摘要）

> 完整决策矩阵与可复制代码见仓库内 `docs/DATA_ACCESS.md`（真相源 `DataPipeline/access_guide.py`，运行时 `GET /api/db/access-guide`）。此处仅摘必要判据。

| 诉求 | 通道 id | 判据 |
|---|---|---|
| 探活 / schema / 样例 | `http_diagnostic` | 单次 ≤200 行，只看最新行 |
| 少量 ticker × ≤5 天 | `sqlite_ro_point` | ticker × 交易日 ≤ 100（每 ticker·日经验 2,000 行） |
| 大区间 / 多 ticker | `parquet_duckdb_bulk` | 超上界且 probe 可用（仅覆盖 raw_bdib） |
| 超阈但 Parquet 不可用 | `sqlite_ro_scan` | 按日期分块（块内含全部 ticker），总跨度 ≤ 60 天 |

硬纪律：全程 `mode=ro`；数据根同源；`raw_bdib` 查询必须带前导列；量纲先对齐；`available=False` 必须降级并明示，**不得静默返回空结果**。

---

## 13. 文档维护机制

### 13.1 文档定位

本文是整合层导览，**不是**任何代码事实的真相源。维护原则：真相源变化 → 本文在时效内同步 → 冲突时以真相源为准。修改本文前先核对 §13.2 清单中对应的真相源。

> **副本同步提示（EMSXView 侧）**：真相源更新后，须将真相源全文（除其头部外）整体覆盖同步到本仓库副本 `docs/EMSXDataPipeline-TECHNICAL_GUIDE.md`，并更新该副本头部的「同步状态」行。本节 §13.2/§13.3 的每周核对与触发式更新在 EMSXDataPipeline 仓库执行；同步动作随其自然发生，无需在本仓库重复核对。

### 13.2 每周例行更新（固定核对清单）

**节奏**：每周第一个工作日执行一次全量核对（建议周一，可在仓库变更记录中按团队节奏调整）。核对 = 逐项比对「本文描述 ↔ 真相源当前值」，漂移即修。

| 核对项 | 本文章节 | 真相源 | 核对方法 |
|---|---|---|---|
| 阶段链与默认开关语义 | §2.3 / §5.0 | `orchestration/core.py::create_daily_e2e_pipeline`、`__main__.py` | 读组装代码；跑 `--once` 看阶段日志 |
| 配置常量/开关/阈值 | §3.2 | `DataPipeline/config.py`（含各常量注释） | diff 常量表；注意新增常量是否补入 |
| 公开 API 符号 | §1.4 | `DataPipeline/__init__.py` | 比对导出清单 |
| 库/表清单与关键索引 | §2.2 / §7.3 | `docs/DATABASE_MANUAL.md`、`storage/schema/`（EXPECTED_VERSIONS、migrations） | 比对迁移目录与 user_version 期望值 |
| Runner 端点与行为 | §9.2 / 附录 B | `runner/app.py`、`runner/db_routes.py` | 比对路由表；`GET /status`、`/api/db/access-guide` 实测 |
| 取数通道阈值 | §12 | `DataPipeline/access_guide.py` | 比对阈值常量 |
| 衍生指标口径 | §5.4 / §5.10 | `fill_bdib_integrated.py`、`analysis/attribution/` | 比对列清单与公式 |
| 守卫阈值 | §6.4 | `config.py` 守卫段 + `pipeline_guards/` | 比对默认值 |
| 维护数据集清单 | §9.5 | `maintenance/registry.py` | 比对 7 项及策略 |
| 日更步骤顺序 | §9.3 | `scripts/daily_update.py::run_daily_pipeline` | 比对步骤序列 |
| 交易前优化项状态 | §11 | 对应入口代码 | 已落地的项移入正文并标注版本 |

每周核对后在 §13.5 变更记录追加一行（即使无变化：`YYYY-MM-DD 周核对，无漂移`），保证核对连续性可审计。

### 13.3 不定期更新：触发条件、判定标准与更新范围

以下任一触发条件命中（判定标准全部以 git diff / 代码事实为准，不凭记忆），须在**1 个工作日内**更新本文对应章节：

| # | 触发事件 | 判定标准（满足其一即触发） | 更新范围 |
|---|---|---|---|
| T1 | 阶段链变化 | `create_daily_e2e_pipeline` 注册序列变化；Stage 类增删/重命名；`--once` 默认语义变化 | §2.3、§5.0 及受影响小节 |
| T2 | 配置契约变化 | `config.py` 新增/删除/改默认值的常量（尤其 `BDIB_EXCHANGE`、保留窗口、守卫阈值等影响不可逆决策者——须同时核对其 `[实测状态]` 注释） | §3.2、引用该值的章节 |
| T3 | 存储契约变化 | `EXPECTED_VERSIONS` 升位；新表/新列/主键/索引变化；`DATABASE_MANUAL.md` 更新 | §2.2、§7；表级细节可只改引用不复制 |
| T4 | 运行时接口变化 | Runner 端点增删/参数/返回结构变化；CLI 参数变化；端口变化 | §9、附录 B、§12 |
| T5 | 采集策略变化 | Bloomberg 字段清单、去重键、fetch_log 状态机、安全日期规则、FX 降级链、白名单、配额机制变化 | §4 |
| T6 | 护栏/守卫变化 | 新增守卫、阈值变化、熔断规则变化、校验策略矩阵变化 | §6 |
| T7 | 跨仓契约变化 | 下游镜像同步（EMSXView `data_access`）要求的契约变化；公开 API 6 符号增删 | §1、§12 |
| T8 | 事故修复引入新机制 | 变更记录中出现「守卫/兼容层/回填/口径修复」类条目（如量纲守卫、bloomberg_compat 的先例） | 对应机制章节 + §8 降级总表 |

**更新范围最小化原则**：只改受影响章节与 §13.5 变更记录；不借机重写无关内容。若某变化同时使「真相源文档」需要改动（如 BUSINESS_FLOW、DATA_ACCESS），先改真相源再同步本文——本文不得与真相源产生第二份口径。

### 13.4 更新流程与自检

1. 定位触发项（T1–T8）→ 2. 读对应真相源确认新事实 → 3. 修改本文受影响章节 → 4. 文档头「文档版本」递增并注明对应项目版本 → 5. §13.5 追加变更记录（触发项编号 + 一句话）→ 6. 自检：占位符无机器路径、无敏感信息（凭证/密钥/用户名/内网拓扑）、代码标识符与真相源拼写一致、§13.2 清单相关行全部重核。

### 13.5 变更记录

| 日期 | 版本 | 触发 | 摘要 |
|---|---|---|---|
| 2026-10-20 | 1.0 | 首版 | 基于 v1.1.0 代码事实整理；覆盖端到端获取/处理/护栏/存储/运行时/交易前供给链路与优化路径 |

---

## 附录 A：术语表

| 术语 | 含义 |
|---|---|
| EMSX / GetFills | Bloomberg 执行管理系统 / 成交查询接口 |
| BDIB | Bloomberg 逐日日内行情（本仓库取 10 秒 bar） |
| fills / orders / routes | 成交 / 订单 / 路由三层实体 |
| source_date / order_as_of_date | 拉取日 / 真实交易日（增量维度，二者不可混用） |
| DFD | Done For Day（订单终态事件，非成交，S2 过滤） |
| equ_ticker / ccy_ticker | Bloomberg 股票复合代码 / 货币期货代码 |
| algo | 由 Broker×StrategyType 归类的执行算法类别（vwap/twap/pov/close/other） |
| VWAP / IS slippage | 成交量加权均价基准 / 实现 shortfall 滑点 |
| ADV | 平均日成交量（5d/20d） |
| regime | 市场状态分类（vol / liquidity / trend 三维） |
| PWP / RPM | 参与率档位 / 相关执行指标（TCA Phase1） |
| TCA | 交易成本分析（Transaction Cost Analysis） |
| AccessTier | READ/WRITE 访问分层（SQL 正则权限） |
| GuardPipeline | 护栏包装器（校验/熔断/日志注入） |
| Runner | 常驻 FastAPI 服务（触发管道 + 只读诊断 + 前端托管） |
| quota_pause | Bloomberg 额度类故障的全局暂停标记 |
| outdated tombstone | 无行情 ticker 的持久化跳过墓碑 |
| freshness SLA | 核心库数据新鲜度阈值（按交易日计量） |
| manifest | `market_fetch_manifest.json` 下游增量通知 |

## 附录 B：Runner 端点清单（速查）

| 方法 | 路径 | 关键约束 |
|---|---|---|
| POST | `/run` | 运行中重复触发 409；`include_fetch=1` 切日更脚本 |
| GET | `/status` | 见 §9.2 字段表 |
| GET | `/health` | — |
| GET | `/maintenance/status` | 维护清单状态 |
| POST | `/maintenance/sync` | 409 幂等；`?force` 强制 |
| GET | `/api/db/overview` | 全库概览 |
| GET | `/api/db/{key}/summary` | `date_limit ≤ 3650` |
| GET | `/api/db/{key}/integrity` | 完整性检查 |
| GET | `/api/db/{key}/tables/{t}/schema` | 表结构 |
| GET | `/api/db/{key}/tables/{t}/sample` | `limit ∈ [1, 200]`（默认 50），**非取数接口** |
| GET | `/api/db/access-guide` | 通道决策矩阵（含 Parquet 实时可用性） |

## 附录 C：仓库内深读文档导航

> （EMSXView 副本注：以下路径均位于 EMSXDataPipeline 仓库内，外部 Agent 无源码访问权限时以本副本为准；有权限者按此导航深读。）

| 文档 | 内容 |
|---|---|
| `README.md` | 定位、快速开始、依赖、配置项、能力边界、免责声明 |
| `AGENTS.md` | 下游取数纪律 + 仓库开发指引 + 变更记录（事故复盘高价值） |
| `DataPipeline/BUSINESS_FLOW.md` | 阶段内部实现、字段语义、护栏细节、历史修复记录 |
| `docs/DATABASE_MANUAL.md` | 10 库全部表/列/类型/关联 |
| `docs/DATA_ACCESS.md` | 取数通道决策矩阵、批量导出、数据陷阱清单 |
| `docs/spec/011-autostart-and-maintenance-sync.md` | 启动编排与维护同步设计 |
| `docs/spec/adr/` | 架构决策记录（0014 死代码清理、0016 数据外置与只读拆分等） |
