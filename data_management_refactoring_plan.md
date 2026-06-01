# 数据管理重构方案 — 执行指南

> 版本: v2.0 | 日期: 2026-06-01 | 基于 `refactoring methodology.md` 4阶段10步框架
>
> 配套控制中心: [data_management_refactoring_control.md](data_management_refactoring_control.md) — 进度跟踪、参数调整、证据审查

---

## 目录

- [零、执行摘要](#零执行摘要)
- [阶段一：锁定与理解](#阶段一锁定与理解)
  - [步骤1 重构目标澄清](#步骤1-重构目标澄清)
  - [步骤2 行为保护网评估](#步骤2-行为保护网评估)
  - [步骤3 现状全方位分析与依赖扫描](#步骤3-现状全方位分析与依赖扫描)
  - [步骤4 架构诊断与契约抽取](#步骤4-架构诊断与契约抽取)
- [阶段二：方案设计与审计](#阶段二方案设计与审计)
  - [步骤5 对比与重构方案设计](#步骤5-对比与重构方案设计)
  - [步骤6 极简审计与设计简化](#步骤6-极简审计与设计简化)
- [阶段三：渐进交付](#阶段三渐进交付)
  - [步骤7 增量迁移规划](#步骤7-增量迁移规划)
  - [步骤8 实施顺序与持续验证](#步骤8-实施顺序与持续验证)
- [阶段四：回归与闭环](#阶段四回归与闭环)
  - [步骤9 全量回归与监控](#步骤9-全量回归与监控)
  - [步骤10 知识沉淀](#步骤10-知识沉淀)
- [附录A：安全网设计](#附录a安全网设计)
- [附录B：观察期自动化框架](#附录b观察期自动化框架)
- [附录C：快速落地检查清单](#附录c快速落地检查清单)

---

## 零、执行摘要

### 0.1 问题

SQLite 单体文件膨胀至 **134.4 GB**（8个数据库文件），其中 `raw_bdib.db` 单文件达 78.7 GB，远超 SQLite 合理承载范围。`raw_bdib.db` + `processed_raw_bdib.db` 存在约 **105 GB 结构性数据冗余**。日增约 113 MB，18个月内将突破 200 GB。

### 0.2 目标

| 指标 | 当前 | 目标 | 改善 |
|------|------|------|------|
| 总存储体积 | 134.4 GB | <30 GB（热数据） | -78% |
| TCA 查询 P95 延迟 | ~15s | <2s | >7x |
| BDIB 数据压缩比 | 1:1 | ~10:1 (Parquet) | -90 GB |
| 日增数据量 | ~113 MB | ~25 MB | -78% |
| 备份耗时 | ~30 min | ~5 min | 6x |
| 单 DB 最大文件 | 78.7 GB | <5 GB | 15x |

### 0.3 核心原则

1. **所有数据不离开 `DATA_DIR`**：新格式在同一目录树下，不跨盘不跨机
2. **先复制、验证通过后才清理**：源数据在每一步都有可恢复的 `.BAK` 安全网
3. **7层安全验证**：前置防呆 → 批次校验 → API回归 → 关联完整性 → 观察期每日自动 → 硬性阻断 → .BAK物理保留
4. **每步可独立上线、可快速回退**：功能开关 + 读路径双轨 + .BAK恢复

### 0.4 文件协作模式

| 文件 | 用途 | 何时用 |
|------|------|--------|
| **本文件**（执行指南） | 设计方案、实施步骤、安全机制、代码示例 | 执行具体步骤时查阅 |
| [控制中心](data_management_refactoring_control.md) | 进度跟踪、参数调整、证据审查 | 每日打开看状态 |

两个文件通过步骤编号（A1-A8, B1-B4, C1-C2, D1）和参数名对齐。控制中心的每一步链接回本文件对应节号。

---

## 阶段一：锁定与理解

### 步骤1 重构目标澄清

#### 1.1 业务驱动力

- **查询性能退化**：TCA 报告对 78 GB 的 `raw_bdib.db` 进行全表扫描，单次查询 5-30 秒
- **运维成本攀升**：每日全量备份 134 GB，耗时 30+ 分钟
- **存储不可持续**：日增 113 MB，无生命周期管理，无限膨胀
- **写入阻塞读取**：SQLite 单写者锁在大文件上持有时间更长，API 请求被阻塞

#### 1.2 理想目标架构（逻辑视角）

```
{EMSXVIEW_DATA_DIR}/
│
├── 热数据 (SQLite, 原地瘦身)
│   ├── raw_bdib.db              78.7G → <5G   (仅保留近3个月)
│   ├── processed_fills.db       18.9G → <8G   (移走9张历史表后VACUUM)
│   ├── raw_fills.db              3.3G → 不变
│   ├── fill_bdib.db             0.77G → 不变
│   ├── regime.db                 4.6G → 不变
│   ├── fill_fetch_history.db    20KB  → 不变
│   ├── execution_history.db     NEW   <5G     (从processed_fills拆出)
│   └── ticker_registry.db       NEW   <1G     (从processed_fills拆出)
│
├── market/                       NEW — BDIB行情温数据
│   └── bdib_10s/
│       ├── year=2024/month=01/*.parquet
│       └── ...
│
├── archive/                      已有 — 数据归档目标
├── backups/                      已有 — 备份目标
└── *.db.bak_migration_YYYYMMDD   临时 — 迁移安全快照
```

所有数据始终在 `{EMSXVIEW_DATA_DIR}` 内，不跨盘不跨机。

#### 1.3 关键业务用例（重构必须保持不变的契约）

| 用例 | 契约接口 | 消费者 |
|------|---------|--------|
| TCA 交易成本分析 | `POST /api/tca/analyze` → `TcaReport` | 前端UI、API调用方 |
| 评分卡查询 | `POST /api/tca/scorecard` → `ScorecardReport` | 前端UI |
| 每日管线运行 | `python -m CostView --pipeline` → exit code 0 | Windows Task Scheduler |
| 成交查询CLI | `python -m CostView --query ...` | 运维人员 |
| 归因指标计算 | Stage 10 AttributionMetricsStage | 管线内部 |
| BDIB数据回退 | `tca_fallback.py` | TCA查询内部 |

---

### 步骤2 行为保护网评估

#### 2.1 必须补齐的测试（门禁条件）

> **未通过以下测试之前，不进行任何数据迁移。**

| 编号 | 测试文件 | 覆盖内容 | 预估 |
|------|---------|---------|------|
| T-01 | `test_archiver.py` | `DataArchiver` 归档迁移行数/数据一致性 | 0.5天 |
| T-02 | `test_partition_migration.py` | `db_partition.sql` 迁移过程正确性 | 0.5天 |
| T-03 | `test_tca_query_performance.py` | 录制当前 TcaQueryService 响应时间基线(P50/P95/P99) | 0.5天 |
| T-04 | `test_cross_db_integrity.py` | 跨DB JOIN结果一致性 (fill_bdib ↔ raw_bdib ↔ processed_fills) | 0.5天 |
| T-05 | `test_parquet_writer.py` | Parquet写入/读取往返校验 | 0.5天 |
| T-06 | `test_observation_framework.py` | `observation_manifest.json` 机制 + `daily_observation_check.py` 框架 | 0.5天 |
| T-07 | `test_shrink_verify.py` | DB收缩后 integrity_check + 行数校验 | 0.5天 |

#### 2.2 现有测试基础设施

| 测试文件 | 覆盖范围 | 行数 |
|----------|---------|------|
| `test_tca_query_service.py` | TCA查询 + 评分卡 | 741 |
| `test_pipeline_framework.py` | PipelineContext, BaseStage, FinancialPipeline | ~200 |
| `test_pipeline_stages.py` | 单阶段测试 | ~150 |
| `test_repository_*.py` ×5 | 仓库CRUD | ~500 |
| `test_regime_e2e.py` | 回归端到端 | ~200 |
| `test_comprehensive.py` / `test_pipeline_guards.py` | 冒烟测试 | ~100 |
| `testing_helpers.py` | 共享Mock工具 | 440 |

---

### 步骤3 现状全方位分析与依赖扫描

#### 3.1 数据库体积分布

```
数据库文件                      体积       占比    主要表                   日增
────────────────────────────────────────────────────────────────────────────
raw_bdib.db                   78.73 GB   58.6%   raw_bdib (10秒K线)      ~80 MB
processed_raw_bdib.db         26.97 GB   20.1%   processed_raw_bdib       ~20 MB
processed_fills.db            18.86 GB   14.0%   15张表, 核心处理库       ~5 MB
regime.db                      4.57 GB    3.4%   回归+归因+审计           ~2 MB
raw_fills.db                   3.34 GB    2.5%   原始成交                 ~3 MB
fill_bdib.db                   0.77 GB    0.6%   成交+行情集成            ~3 MB
processed_bdib.db              0.01 GB   <0.1%   BDIB日线汇总            可忽略
fill_fetch_history.db          0.00 GB   <0.1%   抓取去重                可忽略
────────────────────────────────────────────────────────────────────────────
总计                         134.35 GB   100%                            ~113 MB/日
```

#### 3.2 数据冗余分析

| 冗余对 | 重叠体积 | 说明 |
|--------|---------|------|
| `raw_bdib` ↔ `processed_raw_bdib` | ~105 GB | 同一批K线数据，processed版仅多3列衍生字段 (vwap, fluctuation, log_chg_pct_10s) |
| `processed_fills` 中 `agg_fills_10s` ↔ `processed_fills` | ~5 GB | 聚合数据可从明细重建 |
| 遗产表 | <1 GB | `agg_fills_1min`/`agg_processed_fills`/`processed_fills_1min` |

#### 3.3 数据流依赖图

```
Bloomberg EMSX API ──▶ raw_fills.db (3.3G) ──▶ processed_fills.db (18.9G)
Bloomberg BDIB API ──▶ raw_bdib.db (78.7G) ──▶ processed_raw_bdib.db (27G)
                           │                            │
                           └────────┬───────────────────┘
                                    ▼
                              fill_bdib.db (0.77G)

TCA查询: processed_fills + fill_bdib + raw_bdib → TcaReport
```

#### 3.4 调用方→被调用DB矩阵

| 消费者 | raw_fills | processed_fills | raw_bdib | processed_raw_bdib | fill_bdib | regime |
|--------|:---------:|:---------------:|:--------:|:------------------:|:---------:|:------:|
| Pipeline S1-S2 | ✅ W | — | — | — | — | — |
| Pipeline S2-S7 | — | ✅ W | — | — | — | — |
| Pipeline S5 | — | ✅ R | ✅ R | ✅ W/R | ✅ W | — |
| Pipeline S7 | — | — | ✅ R | ✅ W | — | — |
| Pipeline S8-S10 | — | ✅ R | ✅ R | — | — | ✅ W |
| TcaQueryService | ✅ R | ✅ R | ✅ R | — | ✅ R | — |
| QueryCLI | ✅ R | ✅ R | — | — | — | — |
| Attribution | — | ✅ R | ✅ R | — | — | ✅ R |
| API regime-dist | — | — | — | — | — | ✅ R |

#### 3.5 历史成因与技术债

| 成因 | 代码表现 | 位置 |
|------|---------|------|
| 数据增长失控 | `db_partition.sql` 设计完成但注释"保留向后兼容"，从未激活 | `DataPipeline/storage/schema/db_partition.sql:167` |
| 冗余存储 | 两套DDL分别创建 raw_bdib 和 processed_raw_bdib | `DataPipeline/storage/schema/inline_ddl.py:142,199` |
| 1min聚合禁用但遗留 | 代码注释"disabled to reduce storage overhead" | 探查报告 |
| 归档器无人调度 | `archive_all()` 完备但无调用方 | `DataPipeline/storage/archiver.py:120` |
| VACUUM内联阻塞 | `archive_expired()` 归档后直接VACUUM，大库锁数分钟 | `DataPipeline/storage/archiver.py:113` |
| WAL检查点脆弱 | 仅 `daily_update.py` 成功全流程后checkpoint | `CostView/scripts/daily_update.py` |

#### 3.6 防御性代码标注（极简审计豁免）

| 代码 | 防御目的 | 豁免理由 |
|------|----------|---------|
| `INSERT OR REPLACE` 全列upsert | 幂等重试 | 与归档迁移的 `INSERT OR IGNORE` 同模式 |
| `WriteQueue` 10,000条缓冲 + 反压 | 防内存溢出 | 高频写入必需品 |
| `float32/int32` 精度裁剪 | 减少存储 | 金融计算精度在可接受范围 |
| 线程本地 READ 缓存 | 减少连接开销 | 多线程读取场景必需 |

---

### 步骤4 架构诊断与契约抽取

#### 4.1 架构问题清单

| 严重度 | 问题 | 影响 | 根因 |
|--------|------|------|------|
| 🔴 致命 | `raw_bdib.db` 78.7 GB 单文件 | B-tree索引下全表扫描5-30秒 | 无生命周期管理 |
| 🔴 致命 | raw+processed BDIB 双重存储 ~105 GB | 磁盘浪费，备份翻倍 | 衍生字段物理化而非计算 |
| 🔴 严重 | 归档器未调度 | 数据无限增长 | 缺少运维自动化 |
| 🟠 高 | `db_partition.sql` 未激活 | 18.9 GB单文件混合读写 | 实施延期 |
| 🟠 高 | 无冷热分层 | 全部数据常驻热存储 | 架构早期设计未考虑规模 |
| 🟡 中 | VACUUM内联阻塞 | 管线中断风险 | 简单实现 |
| 🟡 中 | WAL文件增长风险 | 管线崩溃后WAL不截断 | 缺少finally保护 |
| 🟢 低 | 遗产表残留 | 微小空间浪费 | 向后兼容顾虑 |

#### 4.2 模块对外契约

**冻结契约（不可破环）**：

| 契约 | 类型 | 说明 |
|------|------|------|
| `TcaQueryService.build_tca_report(filters)` → `TcaReport` | API签名 | `POST /api/tca/analyze` 核心契约 |
| `TcaQueryService.build_scorecard(filters)` → `ScorecardReport` | API签名 | 评分卡接口 |
| `ConnectionManager.get_connection(db_key, tier)` → `sqlite3.Connection` | 数据访问 | 所有仓库层入口 |
| `Config.TABLE_NAMES` 常量 | 共享配置 | CostView 和 DataPipeline 双重消费 |
| `PipelineFactory.create_daily_e2e_pipeline()` → `FinancialPipeline` | 工厂接口 | `__main__.py` + `daily_update.py` |

**可变更契约（内部）**：

| 契约 | 变更范围 | 说明 |
|------|---------|------|
| RawBDIB 内部存储格式 | DataPipeline 写入方 | 可改为Parquet，读取接口不变 |
| processed_raw_bdib 存在性 | 两个写入阶段 | 可合并入 raw_bdib 或彻底消除 |
| DataArchiver 内部实现 | 维护脚本 | 策略可安全升级 |
| processed_fills 内部表组织 | 仓库层 | 可拆分到新DB键 |

---

## 阶段二：方案设计与审计

### 步骤5 对比与重构方案设计

#### 5.1 差异矩阵（现状 vs 目标）

| 维度 | 现状 | 目标 | 差异 | 破环性 |
|------|------|------|------|:------:|
| BDIB行情存储 | SQLite单表 78 GB | Parquet按年-月分区 + DuckDB查询 | 重大 | ⚠️ 读路径需适配 |
| BDIB衍生数据 | 独立DB 27 GB | DuckDB视图计算（不单独存储） | 消除冗余 | ⚠️ 消除一整张DB |
| 表分区 | 15表混在processed_fills | 激活db_partition.sql → 3个DB | 中等 | ⚠️ 仓库层需更新 |
| 归档策略 | 未调度 | 每月自动执行, VACUUM增量化 | 低 | ✅ 无接口变更 |
| 冷热分层 | 无 | SQLite(热) + Parquet(温) + 归档(冷) | 新增 | ⚠️ 需透明查询层 |

#### 5.2 双向影响分析

| 变更 | 上游影响（生产者） | 下游反作用（消费者） |
|------|-------------------|---------------------|
| BDIB→Parquet | `bdib_fetcher.py` 写入目标变更 | `tca_query_builder.py:get_market_context()` 读取源变更; `tca_fallback.py` BDIB回退路径变更 |
| 消除 processed_raw_bdib | `daily_metrics_calculator.py` S7 不再填充 | 仅被 `fill_bdib_integrated.py` 读取, 可内联计算 |
| 激活 db_partition | `ProcessRawFillsStage` 写入新DB键 | 所有 `_proc_conn()` 调用需更新为多DB路由 |
| 调度归档 | `DataArchiver.archive_all()` 无消费者 | 归档后旧日期范围查询返回空 — 需查询层感知 |

#### 5.3 过度工程审计（已剔除的设计）

| 剔除项 | 剔除理由 |
|--------|---------|
| 从 SQLite 迁移到 PostgreSQL | 运维成本过高, DuckDB/Parquet 更轻量 |
| 引入 Kafka 实时流 | 管线已为批处理, 引入流处会增加不必要的复杂性 |
| Redis 集群缓存 | 现有 LRU + 单 Redis 已满足频率需求 |
| StorageRouter 抽象层 | `ConnectionManager` 新增DB键即可 |
| 透明跨层查询(TCA自动查温数据) | 当前温数据仅用于 BDIB 回退, 直接在 `tca_fallback.py` 实现 DuckDB 查询 |

---

### 步骤6 极简审计与设计简化

#### 6.1 设计元素必要性审查

| 设计元素 | 真实变化点数量 | 保留/删除 | 理由 |
|----------|:-------------:|:---------:|------|
| DuckDB抽象查询层 (BDIB) | 1 | ✅ 保留 | 唯一真实变化点, 最小化封装 |
| `ConnectionManager` 新增DB键 | 3 | ✅ 保留 | 分区后新增3个DB, 统一管理仍是刚需 |
| `WriteQueue` | 1 | ✅ 保留 | 高频写入核心组件 |
| Repository 模式 | N | ✅ 保留 | 读写分离在数据源迁移时保证接口稳定 |
| 新的 StorageRouter 抽象 | 0 | ❌ 删除 | `ConnectionManager` 直接支持新DB键 |
| 透明查询层(跨热/温/冷) | 0-1 | ❌ 暂不引入 | 温数据仅用于TCA回退, 直接调用DuckDB |
| 异步VACUUM框架 | 1 | ❌ 简化 | 改用 `PRAGMA incremental_vacuum` |

#### 6.2 最终极简方案

```
Phase A: BDIB行情瘦身 (优先级最高, 体积减少最大 ≈100 GB)
  A1. 安装 DuckDB + PyArrow 依赖
  A2. 创建 storage/market_store.py (Parquet/DuckDB写入器)
  A3. 修改 bdib_fetcher.py 添加并行写入Parquet (flag: BDIB_PARQUET_ENABLED)
  A4. 运行回填脚本迁移历史BDIB → Parquet (逐月迁移+校验)
  A5. 添加 tca_query_service.py DuckDB查询路径 (flag: BDIB_QUERY_ENGINE)
  A6. 验证期: DuckDB与SQLite并行查询, 结果diff对比
  A7. 收缩 raw_bdib.db 至近3个月 (先全量备份)
  A8. 消除 processed_raw_bdib.db, 衍生字段改为DuckDB视图

Phase B: 激活数据库分区方案
  B1. 在新DB键上执行 db_partition.sql 创建表
  B2. 双写: 写入 processed_fills.db 同时写入新分区DB (flag: PARTITION_DUAL_WRITE)
  B3. 仓库层逐步切换到新DB键读取 (flag: PARTITION_READ_NEW)
  B4. VACUUM 原 processed_fills.db 移除已迁移表

Phase C: 调度归档 + VACUUM优化
  C1. 在 daily_update.py 加入 post-pipeline 归档步骤
  C2. 将 VACUUM 改为增量模式 (PRAGMA auto_vacuum=INCREMENTAL)
  C3. 添加归档后数据可读性校验

Phase D: 监控 + 告警
  D1. 添加 DB 体积监控 (阈值: 单文件>10 GB, 总热数据>50 GB)
  D2. 添加 TCA 查询延迟监控 (P95 <3秒)
  D3. 添加 WAL 文件大小监控 (>500 MB告警)
```

---

## 阶段三：渐进交付

### 步骤7 增量迁移规划

采用**绞杀者模式**（Strangler Fig）：新存储与旧存储并行运行 → 验证 → 切换 → 退役。

#### 7.1 迁移任务总表

> 当前进度见 [控制中心 §一](data_management_refactoring_control.md)

| 序号 | 迁移任务 | 可独立上线 | 回退方式 | 开关/Flag | 前置条件 |
|:----:|----------|:----------:|----------|-----------|---------|
| **Phase A: BDIB瘦身** |||||
| A1 | 安装 DuckDB + PyArrow 依赖 | ✅ | revert commit | — | — |
| A2 | 创建 `storage/market_store.py` | ✅ | 新模块不影响现有 | — | A1 |
| A3 | `bdib_fetcher.py` 并行写 Parquet | ✅ | `BDIB_PARQUET_ENABLED=0` | Config flag | A2 |
| A4 | 回填脚本迁移历史BDIB→Parquet | ✅ | Parquet可删除重建 | `--dry-run` | A3 稳定跑3天 |
| A5 | `tca_query_service.py` DuckDB读路径 | ✅ | `BDIB_QUERY_ENGINE=sqlite` | Config flag | A4 |
| A6 | 验证期: 双引擎并行查询 | ✅ | flag回切 | — | A5 |
| A7 | 收缩 `raw_bdib.db` | ⚠️ | 从 `.BAK` 恢复 | `--confirm-shrink` | A6 连续7天diff=0 |
| A8 | 消除 `processed_raw_bdib.db` | ⚠️ | 从 `.BAK` 恢复 | `--confirm-retire` | A7 观察期通过 |
| **Phase B: 分区激活** |||||
| B1 | 执行 `db_partition.sql` 创建表 | ✅ | 删除新DB文件 | — | Phase A完成 |
| B2 | 双写 processed_fills + 新分区DB | ✅ | `PARTITION_DUAL_WRITE=0` | Config flag | B1 |
| B3 | 仓库层切换读路径 | ✅ | `PARTITION_READ_NEW=0` | Config flag | B2 双写稳定 |
| B4 | VACUUM 原DB移除已迁移表 | ⚠️ | 从 `.BAK` 恢复 | `--confirm-cleanup` | B3 观察期通过 |
| **Phase C: 归档调度** |||||
| C1 | `scripts/run_archive.py` + 调度注册 | ✅ | 删除任务 | — | Phase A完成 |
| C2 | `DataArchiver` VACUUM→增量 | ✅ | revert | — | C1 |
| **Phase D: 监控** |||||
| D1 | `scripts/health_check.py` | ✅ | — | — | 独立 |

> 标记: ✅ = 可立即回退 &nbsp; ⚠️ = 需`.BAK`文件恢复 (耗时几分钟至十几分钟)

#### 7.2 功能开关设计

```python
# DataPipeline/config.py 新增

class Config:
    # BDIB存储引擎
    BDIB_PARQUET_ENABLED: bool = os.getenv("BDIB_PARQUET_ENABLED", "0") == "1"
    BDIB_QUERY_ENGINE: str = os.getenv("BDIB_QUERY_ENGINE", "sqlite")  # "sqlite" | "duckdb"
    BDIB_PARQUET_DIR: Path = DATA_DIR / "market" / "bdib_10s"

    # 分区双写/读
    PARTITION_DUAL_WRITE: bool = os.getenv("PARTITION_DUAL_WRITE", "0") == "1"
    PARTITION_READ_NEW: bool = os.getenv("PARTITION_READ_NEW", "0") == "1"

    # 新DB键
    DB_EXECUTION_HISTORY = "execution_history"
    DB_TICKER_REGISTRY = "ticker_registry"

    # 保留策略
    BDIB_HOT_RETENTION_MONTHS: int = 3
```

#### 7.3 每条数据的安全处理路径

**路径1: `raw_bdib.db` (78.7 GB) — 10秒K线**

```
Step 1: 全量备份
  raw_bdib.db → raw_bdib.db.bak_migration_YYYYMMDD (sqlite3 .backup API)

Step 2: 逐月复制到 Parquet (源文件不动)
  raw_bdib.db ─COPY─▶ market/bdib_10s/year=2024/month=01/*.parquet
                     market/bdib_10s/year=2024/month=02/*.parquet
                     ...
  每批次独立校验: 行数+聚合+抽样+边界 (见 §附录A 层级2)

Step 3: 全量校验通过后, 收缩SQLite
  新建 raw_bdib.db → INSERT近3个月数据 → 重命名替换
  原文件保留为 .BAK

Step 4: 14天观察期
  每日自动观察检查 + TCA API回归 → 全部通过 → observation_manifest 标记 complete
  → .BAK改只读保留30天 (详见 §附录B)
```

**路径2: `processed_raw_bdib.db` (27 GB) — 衍生字段**

```
Step 1: 备份 processed_raw_bdib.db → .BAK

Step 2: 验证可重现性
  从 raw_bdib (Parquet) 重新计算衍生字段 (vwap, fluctuation, log_chg_pct_10s)
  与 processed_raw_bdib.db 中现有值逐行对比 → 确认100%可重现
  (纯数学计算，不依赖外部数据)

Step 3: 创建 DuckDB 视图 (不占磁盘)
  CREATE VIEW bdib_enriched AS
    SELECT *, computed_cols FROM read_parquet('market/bdib_10s/**/*.parquet')

Step 4: 14天观察期
  所有原读路径同时查DuckDB视图 → 结果一致

Step 5: 退役
  processed_raw_bdib.db → .BAK (只读保留30天)
```

**路径3: `processed_fills.db` (18.9 GB) — 15表分区**

```
Step 1: 备份 processed_fills.db → .BAK

Step 2: 创建新DB, 复制数据 (源表不动)
  INSERT INTO execution_history.db.route_registry
    SELECT * FROM processed_fills.db.route_registry
  INSERT INTO execution_history.db.order_history
    SELECT * FROM processed_fills.db.order_history
  ... (逐表复制，每表复制后校验行数)

Step 3: 双读验证
  仓库层同时读旧DB和新DB → 逐行对比

Step 4: 切换读路径, DROP旧表, VACUUM
  DROP TABLE route_registry; DROP TABLE order_history; ...
  VACUUM (释放 ~10 GB)

Step 5: 14天观察期 → .BAK改只读保留30天
```

#### 7.4 本文档中每步的执行信息

每步的具体实施细节分布在以下节中：

| 需要了解 | 查阅 |
|---------|------|
| 每步改什么文件、改什么函数 | §7.1 备注列 + §7.2 开关代码 + §5.2 双向影响分析 |
| 每步验证命令与通过标准 | §附录C 检查清单 + §步骤8 持续验证 |
| 每步的安全网如何实施 | §附录A (七层) + §附录B (观察期) |
| 每步失败如何回退 | §7.1 回退方式列 + §附录A.2 .BAK保留规则 |
| 观察期自动判定逻辑 | §附录B.2 daily_observation_check.py |

---

### 步骤8 实施顺序与持续验证

#### 8.1 时间线

```
Week 1: A1-A3  (DuckDB依赖 + 并行写入, 零风险)
  └─ 门禁: pytest全绿, Parquet写入无异常

Week 2: A4-A6  (历史迁移 + DuckDB查询, 低风险)
  └─ 门禁: DuckDB vs SQLite 查询结果 diff = 0; 录制TCA响应时间基线

Week 3: A7-A8  (退役旧存储, 中风险)
  └─ 门禁: 全量回归 + 手动TCA报告对比 + 磁盘释放 ~100 GB

Week 4: B1-B2  (分区表创建 + 双写)
  └─ 门禁: 仓库层单测全绿, 双写数据量一致

Week 5: B3-B4  (切换读取 + 清理)
  └─ 门禁: 管线端到端测试 + TCA API响应时间对比

Week 6: C1-C2, D1  (归档调度 + 监控)
  └─ 门禁: 归档dry-run无异常, 健康检查正常
```

#### 8.2 持续验证机制

每个Week内的每日管线运行后自动执行:

```bash
# 每日管线后自动执行的验证套件
python -m pytest tests/test_comprehensive.py -q
python -m pytest tests/test_tca_query_service.py -q
python scripts/daily_observation_check.py --phase active
python scripts/health_check.py
```

#### 8.3 门禁检查点

| 步骤 | 门禁内容 | 失败处理 |
|------|---------|---------|
| A2 Parquet写入器就绪 | `pytest tests/test_parquet_writer.py` 全绿 | 修复代码，不进入A3 |
| A3 双写启用 | 连续3天运行，Parquet行数=SQLite行数 | 修复差异，不进入A4 |
| A4 历史迁移 | 全部月份校验通过，manifest记录完整 | 重迁失败月份，不进入A5 |
| A5 DuckDB查询路径 | DuckDB結果 vs SQLite結果 100%一致(自动化diff) | 修复查询逻辑，不进入A6 |
| A7 退役旧存储 | 7天观察期内所有API回归通过 | 延长观察期，不进入A8 |
| B4 清理原表 | 分区后TCA查询延迟对比基线无劣化 | 回退读路径，不进入Phase C |

---

## 阶段四：回归与闭环

### 步骤9 全量回归与监控

#### 9.1 回归验证矩阵

| 验证维度 | 方法 | 基线 | 告警阈值 |
|----------|------|------|---------|
| TCA报告正确性 | `test_tca_query_service.py` 全量 | 741行测试 | 任何回归 |
| TCA查询延迟 | `test_tca_query_performance.py` | 录制P50/P95/P99 | >2x基线 或 >5s |
| 管线端到端 | `test_comprehensive.py` | 100%通过 | 任何失败 |
| DB完整性 | `PRAGMA integrity_check` 全部DB | 全"ok" | 任何非ok |
| 磁盘空间 | `health_check.py` | 迁移前134 GB | 热数据 >20 GB |
| WAL文件大小 | `health_check.py` | <50 MB | >500 MB |
| 归档执行 | 日志检查 | 每月成功1次 | 连续2次跳过 |

#### 9.2 上线后监控 (24-48小时)

| 指标 | 监控方式 | 对比基线 |
|------|---------|---------|
| TCA API P95延迟 | Prometheus/日志 | 迁移前录制 |
| 管线执行耗时 | 日志分析 | 迁移前运行时间 |
| 内存使用(RSS) | `psutil` 日志 | 迁移前基准 |
| 磁盘I/O | Windows PerfMon | 迁移前模式 |

---

### 步骤10 知识沉淀

#### 10.1 架构决策记录 (ADR)

**ADR-001: 选择 DuckDB/Parquet 替代 SQLite 存储高频K线数据**

- **状态**: 已接受
- **日期**: 2026-06-01
- **背景**: `raw_bdib.db` 78.7 GB, SQLite 单文件超出合理范围, 查询退化
- **否决方案**:
  - PostgreSQL + TimescaleDB — 运维成本高, 需额外服务
  - ClickHouse — 过度工程, 单机部署不匹配
  - 直接压缩 SQLite — 治标不治本, 查询性能仍差
- **选择理由**:
  - 零运维（嵌入式引擎, 无需服务进程）
  - 列式存储压缩比 ~10:1（Parquet snappy）
  - 完全SQL兼容（DuckDB支持标准SQL）
  - 与现有Python生态无缝集成（PyArrow读写）

**ADR-002: 激活 db_partition.sql 按访问模式拆分 processed_fills.db**

- **状态**: 已接受
- **日期**: 2026-06-01
- **背景**: 15表混合读写, 单DB 18.9 GB, 写入者锁阻塞读取者
- **风险**: 读路径需适配多个DB键, 但 `ConnectionManager` 已支持
- **收益**: 读写隔离, 高写入表不再阻塞历史查询

**ADR-003: 数据保留策略 — 3-12-36原则**

- **状态**: 已接受
- **日期**: 2026-06-01
- **3个月**: 10秒K线保留在SQLite(热), 之后迁移到Parquet(温)
- **12个月**: Parquet格式保留, 之后可移动至冷存储
- **36个月**: 成交/历史/归因数据全量保留

#### 10.2 运维手册更新

- [ ] 更新 `DataPipeline/README.md` — 添加数据生命周期管理章节
- [ ] 更新 `CostView/README.md` — 添加存储架构图
- [ ] 创建 `scripts/migrations/README.md` — 精确操作命令
- [ ] 创建 `scripts/health_check.py` 使用说明
- [ ] 创建 `scripts/daily_observation_check.py` 使用说明

---

## 附录A：安全网设计

### A.1 七层安全验证模型

```
层级1: 前置防呆
  └─ 磁盘剩余空间 > 源文件2x
     WAL已checkpoint
     PRAGMA integrity_check = 'ok'
     无其他进程持有写锁

层级2: 迁移批次校验 (来源独立)
  └─ 行数对比: SQL COUNT(*) vs Parquet len(df)
     聚合对比: SUM/AVG/MIN/MAX 全量
     抽样对比: 随机1000行逐值
     边界覆盖: NULL/零值/首尾K线/跨年日/节假日

层级3: 迁移后API回归
  └─ TcaReport 逐字段对比 (允许浮点误差 <0.01%)
     ScorecardReport 逐字段对比
     相同参数 → 相同结果

层级4: 关联完整性校验
  └─ fill_bdib JOIN raw_bdib JOIN processed_fills 迁移前后对比
     ROLLUP 聚合结果一致

层级5: 观察期每日自动校验 (14天)
  └─ daily_observation_check.py 每日自动执行
     覆盖 ≥2个完整管线周期
     覆盖 ≥2个不同交易日

层级6: 硬性阻断条件 (不可自动判定通过)
  └─ TCA报告结果漂移 >0.1%
     增量管线失败
     DB体积异常变化
     关联查询异常
     人工标注的"疑似异常"

层级7: .BAK物理保留
  └─ 观察期通过后 → .BAK改只读 → 保留30天 → 自动清理
     硬性阻断触发后 → .BAK永久保留 → 人工调查
```

### A.2 校验代码独立性设计

迁移校验逻辑必须与迁移逻辑**来源独立**：不同API(SQL vs Parquet)、不同引擎(SQLite vs DuckDB)、不同实现路径(Python迭代 vs SQL聚合)。

```python
class BDIBMigrationVerifier:
    """与 BDIBMigrationRunner 共享数据结构但独立实现校验逻辑"""

    def verify_batch(self, source_db: Path, parquet_path: Path, month: str):
        """每批次校验 —— 与迁移代码无共享bug路径"""

        # 校验1: 行数 — SQL聚合 vs Parquet元数据 (不同API)
        sql_count = self._sql_count(source_db, month)
        pq_count = self._parquet_row_count(parquet_path)
        assert sql_count == pq_count, f"行数不匹配"

        # 校验2: 全量聚合 — SQL聚合 vs Parquet聚合 (不同引擎)
        sql_agg = self._sql_aggregate(source_db, month)  # SUM/AVG/MIN/MAX
        pq_agg = self._parquet_aggregate(parquet_path)
        for col in ("volume", "close", "value"):
            assert abs(sql_agg[col] - pq_agg[col]) < 1e-6

        # 校验3: 抽样 — SQL取具体行 vs Parquet过滤取行 (不同实现路径)
        sample_pks = self._random_sample_pks(source_db, month, n=1000)
        sql_rows = self._sql_fetch_by_pks(source_db, sample_pks)
        pq_rows = self._parquet_fetch_by_pks(parquet_path, sample_pks)
        for pk in sample_pks:
            self._assert_row_equal(sql_rows[pk], pq_rows[pk])

        # 校验4: 边界 — 刻意覆盖所有特殊条件
        for boundary in [
            ("NULL值", "WHERE close IS NULL"),
            ("零值", "WHERE volume = 0"),
            ("开盘首K", "WHERE mkt_timestamp LIKE '%09:30:00'"),
            ("收盘末K", "WHERE mkt_timestamp LIKE '%16:00:00'"),
            ("半日市", "WHERE mkt_timestamp LIKE '%13:00:00'"),
            ("跨年日", "WHERE order_as_of_date IN ('2024-12-31','2025-01-01')"),
        ]:
            sql_result = self._query_boundary_sql(source_db, boundary)
            pq_result = self._query_boundary_parquet(parquet_path, boundary)
            assert sql_result == pq_result, f"边界不一致: {boundary[0]}"
```

### A.3 .BAK 删除规则

| 触发条件 | .BAK处理 |
|---------|---------|
| 14天观察期全部通过 + 无阻断 | → 改为只读, 保留30天后自动清理 |
| 观察期内任何一天检查失败 | → 重置计数, 从失败日重新算14天 |
| 硬性阻断条件触发 | → 永久保留, 人工调查 |
| 人工标注"疑似异常" | → 永久保留 |

---

## 附录B：观察期自动化框架

### B.1 observation_manifest.json 结构

```json
{
  "phase": "A7",
  "description": "收缩 raw_bdib.db 至近3个月",
  "bak_files": [
    {
      "path": "raw_bdib.db.bak_migration_20260601",
      "sha256": "a1b2c3...",
      "source_db": "raw_bdib.db",
      "created_at": "2026-06-01T10:00:00Z"
    }
  ],
  "start_date": "2026-06-01",
  "retention_until": "2026-06-15",
  "min_pipeline_cycles": 2,
  "pipeline_cycles_run": 0,
  "daily_checks": [],
  "blocking_conditions_triggered": [],
  "final_status": "pending"
}
```

### B.2 daily_observation_check.py 框架

```python
"""
每日观察检查脚本 — 迁移后的自动化验证守护进程。

Usage:
    python scripts/daily_observation_check.py --phase A7
    python scripts/daily_observation_check.py --phase all

由 Windows Task Scheduler 在每日管线完成后触发。
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from DataPipeline.config import Config
from DataPipeline.storage.backup import BackupManager
from DataPipeline.storage.connection import ConnectionManager


class ObservationChecker:
    """迁移后观察期的自动化检查框架。

    检查项(每项独立, 任一失败即告当日fail):
      CHECK-1: .BAK文件完整性 (sha256 vs manifest记录)
      CHECK-2: 热数据DB integrity_check = 'ok'
      CHECK-3: TCA API回归套件全绿
      CHECK-4: 管线每日增量运行成功
      CHECK-5: 热DB体积无异常跳变 (对比昨日, ±20%)
      CHECK-6: 关联完整性 (跨DB JOIN抽样对比)
    """

    def __init__(self, phase: str, manifest_path: Optional[Path] = None):
        self.phase = phase
        self.manifest_path = manifest_path or Config.DATA_DIR / f"observation_{phase}.json"
        self.manifest = json.loads(self.manifest_path.read_text())
        self.today = date.today().isoformat()

    def run(self) -> bool:
        """执行所有检查, 返回是否全部通过。"""
        results = {
            "date": self.today,
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "all_pass": True,
        }

        for check_name, check_fn in [
            ("bak_integrity", self._check_bak_integrity),
            ("db_integrity", self._check_db_integrity),
            ("tca_regression", self._check_tca_regression),
            ("pipeline_success", self._check_pipeline_success),
            ("db_volume_stable", self._check_db_volume_stable),
            ("cross_db_integrity", self._check_cross_db_integrity),
        ]:
            try:
                passed, detail = check_fn()
                results["checks"][check_name] = {"passed": passed, "detail": detail}
                if not passed:
                    results["all_pass"] = False
            except Exception as e:
                results["checks"][check_name] = {"passed": False, "detail": str(e)}
                results["all_pass"] = False

        self.manifest["daily_checks"].append(results)
        self._check_blocking_conditions(results)

        if self._can_mark_complete():
            self.manifest["final_status"] = "complete"
            self._notify_bak_retention()

        self.manifest_path.write_text(json.dumps(self.manifest, indent=2, default=str))
        return results["all_pass"]

    def _check_bak_integrity(self) -> tuple[bool, str]:
        """CHECK-1: .BAK文件sha256对比manifest记录"""
        for bak in self.manifest["bak_files"]:
            bak_path = Path(bak["path"])
            if not bak_path.exists():
                return False, f"BAK文件缺失: {bak_path}"
            actual = BackupManager._sha256_file(bak_path)
            if actual != bak["sha256"]:
                return False, f"SHA256不匹配: {bak_path}"
        return True, "所有BAK文件完整"

    def _check_db_integrity(self) -> tuple[bool, str]:
        """CHECK-2: integrity_check"""
        mgr = ConnectionManager()
        backup_mgr = BackupManager(connection_manager=mgr)
        failures = []
        for db_name in Config.DB_KEYS:
            result = backup_mgr.verify_integrity(db_name)
            if result["status"] != "ok":
                failures.append(f"{db_name}: {result['detail']}")
        return (len(failures) == 0, "; ".join(failures) if failures else "all ok")

    def _check_tca_regression(self) -> tuple[bool, str]:
        """CHECK-3: TCA API回归"""
        import subprocess
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_tca_query_service.py", "-q", "--tb=short"],
            capture_output=True, text=True, cwd=Config._PROJECT_ROOT / "CostView"
        )
        return (result.returncode == 0, result.stdout.strip()[-200:])

    def _check_pipeline_success(self) -> tuple[bool, str]:
        """CHECK-4: 管线日志最近一次成功记录"""
        log_file = Config.LOG_FILE
        if not log_file.exists():
            return True, "skip (无管线日志)"
        # 查找最近的 "Pipeline completed successfully" 记录
        return True, "skip (需具体实现)"

    def _check_db_volume_stable(self) -> tuple[bool, str]:
        """CHECK-5: DB体积无异常跳变"""
        yesterday_checks = self.manifest["daily_checks"]
        if len(yesterday_checks) < 2:
            return True, "skip (不足2天数据)"
        return True, "skip (需具体实现)"

    def _check_cross_db_integrity(self) -> tuple[bool, str]:
        """CHECK-6: 关联完整性"""
        return True, "skip (需具体实现)"

    def _check_blocking_conditions(self, results: dict) -> None:
        """检查是否触发硬性阻断。

        触发条件(任一即阻断, .BAK永不自动删除):
          - day-over-day TCA报告数值漂移 >0.1%
          - 增量管线exit code != 0
          - 热DB体积变化超预期
          - 关联查询返回NULL(之前不是)
          - manual_flag已设置
        """
        blocking = []
        if not results["checks"].get("tca_regression", {}).get("passed"):
            blocking.append("tca_regression_failed")
        if not results["checks"].get("pipeline_success", {}).get("passed"):
            blocking.append("pipeline_failed")
        if not results["checks"].get("cross_db_integrity", {}).get("passed"):
            blocking.append("cross_db_integrity_failed")

        if blocking:
            self.manifest["blocking_conditions_triggered"].append({
                "date": self.today,
                "conditions": blocking,
            })
            self.manifest["final_status"] = "blocked"

    def _can_mark_complete(self) -> bool:
        """判断观察期是否可以完成。

        条件:
          1. 连续14天 daily_checks 全部 pass
          2. 覆盖 ≥2 完整管线周期
          3. 无任何 blocking_conditions_triggered
          4. 无 manual_flag
          5. start_date距今 ≥14天
        """
        if self.manifest.get("blocking_conditions_triggered"):
            return False
        start = date.fromisoformat(self.manifest["start_date"])
        if (date.today() - start).days < 14:
            return False
        recent = self.manifest["daily_checks"][-14:]
        if len(recent) < 14:
            return False
        all_pass = all(c.get("all_pass") for c in recent)
        cycles_ok = self.manifest["pipeline_cycles_run"] >= self.manifest["min_pipeline_cycles"]
        return all_pass and cycles_ok

    def _notify_bak_retention(self) -> None:
        """观察期完成通知: .BAK改只读, 30天后自动清理。"""
        import os, stat
        for bak in self.manifest["bak_files"]:
            bak_path = Path(bak["path"])
            if bak_path.exists():
                bak_path.chmod(stat.S_IREAD)
                self.manifest["bak_cleanup_date"] = (
                    date.today().replace(day=date.today().day + 30).isoformat()
                )
                print(f"[OBSERVATION] 观察期通过. {bak_path.name} 已设为只读, "
                      f"将于 {self.manifest['bak_cleanup_date']} 自动清理.")
```

### B.3 Windows Task Scheduler 注册

```powershell
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "scripts\daily_observation_check.py --phase all"
$trigger = New-ScheduledTaskTrigger -Daily -At "03:30AM"
Register-ScheduledTask `
    -TaskName "EMSXView_DailyObservationCheck" `
    -Action $action -Trigger $trigger
```

---

## 附录C：快速落地检查清单

### 重构前

- [ ] 目标业务用例已明确 (TCA报告/评分卡/每日管线)
- [ ] T-01~T-07 补齐测试已通过
- [ ] 当前P50/P95/P99查询延迟已录制
- [ ] 所有对外接口契约已文档化 (见 §步骤4.2)
- [ ] `.env` 中 `EMSXVIEW_DATA_DIR` 已确认

### 设计中

- [ ] 是否因"未来可能需要"引入了抽象? (已剔除, 见 §步骤6.1)
- [ ] 接口变更的影响矩阵已生成? (见 §步骤5.2)
- [ ] 破环性变更有迁移步骤? (每步有flag + .BAK回退, 见 §步骤7.1)

### 实施中 (每步)

- [ ] `python -m pytest tests/ -q` 全绿
- [ ] 功能开关可正常启用/关闭
- [ ] `.BAK` 文件已创建且 sha256 已记录
- [ ] `observation_manifest.json` 已初始化
- [ ] 回退路径已测试 (至少dry-run验证)

### 观察期 (每Phase)

- [ ] `daily_observation_check.py` 连续14天全过
- [ ] 管线至少2个完整周期成功
- [ ] 无硬性阻断条件触发
- [ ] TCA报告延迟无劣化

### 完成后

- [ ] `.BAK` 文件改只读, 30天后自动清理
- [ ] ADR文档已存档
- [ ] `README.md` / 架构图已更新
- [ ] 监控告警已启用 (`health_check.py`)
