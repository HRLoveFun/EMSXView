# 数据管理重构 — 控制中心

> 配套执行指南: [data_management_refactoring_plan.md](data_management_refactoring_plan.md) — 详细方案、实施步骤、安全机制
>
> 最后更新: 2026-06-25

本文件三件事：**看进度**、**调参数**、**查证据**。具体"怎么做"全部在执行指南。

---

## 一、进度

> ⚠️ 全部步骤已完成 (2026-07-02)，本表仅作历史记录。运行时参数见 §二。

| # | 任务 | 状态 | 执行指南 | 备注 |
|:--:|------|:----:|---------|------|
| **Phase A: BDIB瘦身** | | | | |
| A1 | 安装 DuckDB + PyArrow 依赖 | ✅ | [§步骤7.1](data_management_refactoring_plan.md#71-迁移任务总表) | |
| A2 | 创建 `storage/market_store.py` | ✅ | 同上 | |
| A3 | `bdib_fetcher.py` 双写 Parquet | ✅ | 同上 | flag: `BDIB_PARQUET_ENABLED`; 实际写路径在 `market_data.py:upsert_bdib_data()` 仓库层 |
| A4 | 历史BDIB回填到Parquet | ✅ | 同上 | 10个月 ✓; 401M行; 85.1GB→6.62GB (12.9:1) |
| A5 | `tca_query_service.py` DuckDB读路径 | ✅ | 同上 | flag: `BDIB_QUERY_ENGINE`; 修改 `tca_query_builder.py` + `tca_fallback.py` |
| A6 | 验证期：双引擎对比 | ✅ | 同上 | 行数401M=401M ✓; 聚合diff<0.0001% ✓; 抽样10/10 ✓ |
| A7 | 收缩 `raw_bdib.db` | ✅ | 同上 + [§7.3路径1](data_management_refactoring_plan.md#73-每条数据的安全处理路径) | 85.1GB→31.2GB (63%); 147M行; integrity=ok; 观察期完成 2026-06-10 (7天all_pass) |
| A8 | 消除 `processed_raw_bdib.db` | ✅ | 同上 + [§7.3路径2](data_management_refactoring_plan.md#73-每条数据的安全处理路径) | 32.0GB释放; DuckDB视图就绪; 可重现性0.0429%; 观察期完成 2026-06-15 (6天all_pass); BAK 已清理 2026-07-02 (sha256 验证通过，释放 29.78 GB) |
| **Phase B: 分区** | | | | |
| B1 | 执行 `db_partition.sql` 创建表 + 复制数据 | ✅ | [§步骤7.1](data_management_refactoring_plan.md#71-迁移任务总表) | 9表100%匹配; execution_history.db + ticker_registry.db 已创建 |
| B2 | 双写新分区DB | ✅ | 同上 | flag: `PARTITION_DUAL_WRITE`; `fills.py._upsert()` + `upsert_order_labels` 已添加双写 |
| B3 | 仓库层切换读路径 | ✅ | 同上 | flag: `PARTITION_READ_NEW`; `_conn_for()` 路由9表读; route_registry JOIN保持原路径 |
| B4 | 清理原DB已迁移表 | ✅ | 同上 + [§7.3路径3](data_management_refactoring_plan.md#73-每条数据的安全处理路径) | 9表DROP ✓; VACUUM 26.38→24.39 GB; 观察期 已完成 2026-06-21 (6天 all_pass，2 个管线周期，无阻断); BAK 已清理 2026-07-02 (提前于原计划 07-21，sha256 验证通过，释放 24.57 GB) |
| **Phase C: 归档** | | | | |
| C1 | `scripts/run_archive.py` + 调度注册 | ✅ | [§步骤7.1](data_management_refactoring_plan.md#71-迁移任务总表) | 集成到 daily_update.py Stage D; 每月调度: `--full`; 管线后自动: `_run_archive_auto()` |
| C2 | `DataArchiver` VACUUM → 增量 | ✅ | 同上 | `PRAGMA auto_vacuum=INCREMENTAL` + `PRAGMA incremental_vacuum(N)` |
| **Phase D: 监控** | | | | |
| D1 | `scripts/health_check.py` (DB体积+WAL+延迟+完整性) | ✅ | [§步骤7.1](data_management_refactoring_plan.md#71-迁移任务总表) | 6项检查; 环境变量可调阈值: `HEALTH_DB_SIZE_GB`, `HEALTH_WAL_MB`, `HEALTH_TCA_LATENCY_S` |

| 全局 | |
|------|----|
| 总进度 | 15/15 |
| 当前阻塞 | 无 · BAK 全部清理完毕 (B4+A8+孤儿，2026-07-02，共释放 57.58 GB) |

> 状态: ⬜ pending &nbsp; ⏳ in_progress &nbsp; ✅ done &nbsp; ⛔ blocked &nbsp; ⊘ skipped

---

## 二、可调参数

修改重构要求时**只改此表**。参数定义见执行指南 [§7.2](data_management_refactoring_plan.md#72-功能开关设计)。

| 参数 | 默认值 | 说明 | 影响步骤 |
|------|-------|------|:--------:|
| `BDIB_HOT_RETENTION_MONTHS` | 3 | SQLite中保留近几个月K线 | A7 |
| `BDIB_PARQUET_ENABLED` | false | 启用BDIB Parquet双写 | A3, A4 |
| `BDIB_QUERY_ENGINE` | duckdb | BDIB查询引擎: `sqlite` / `duckdb` | A5, A6 |
| `PARTITION_DUAL_WRITE` | false | 分区双写开关 | B2 |
| `PARTITION_READ_NEW` | false | 读新分区DB开关 | B3 |
| `PROCESSED_RAW_BDIB_ENABLED` | true | processed_raw_bdib写入开关 (false=退役) | A8 |
| `raw_fills` 保留月数 | 12 | `DataArchiver.ARCHIVE_CONFIG` | C1 |
| `processed_fills` 保留月数 | 24 | 同上 | C1 |
| `raw_bdib` 保留月数 | 12 | 同上 | C1 |
| `fill_bdib` 保留月数 | 24 | 同上 | C1 |
| ~~观察期天数~~ | ~~14~~ | ~~[已关闭 2026-07-02] 迁移后每日自动校验天数~~ | ~~A7, A8, B4~~ |
| ~~BAK保留天数(通过后)~~ | ~~30~~ | ~~[已关闭 2026-07-02] 观察期通过后.BAK只读保留天数，BAK 已全部清理~~ | ~~A7, A8, B4~~ |

---

## 三、验证记录

审查重构结果时，查看以下文件。验收标准见执行指南 [§步骤9](data_management_refactoring_plan.md#步骤9-全量回归与监控)。

| 验证维度 | 证据位置 | 关联步骤 |
|----------|---------|:--------:|
| A4 历史迁移校验 | `scripts/logs/backfill_*.log` + `data/backfill_bdib_manifest.json` | A4 |
| A6 双引擎对比 | `scripts/logs/verify_bdib_*.log` + `data/verify_bdib_manifest.json` | A6 |
| A7 收缩校验 | `scripts/logs/shrink_a7_*.log` | A7 |
| A8 退役校验 | `scripts/logs/retire_a8_*.log` | A8 |
| A8 可重现性 | `scripts/logs/retire_a8_*.log` (抽样对比结果) | A8 |
| A7 观察期 | `data/observation_A7.json` | A7 |
| A8 观察期 | `data/observation_A8.json` | A8 |
| B4 观察期 | `data/observation_B4.json` | B4 |
| 每日观察日志 | `scripts/logs/observation_*.log` | A7, A8, B4 |
| 归档执行日志 | `scripts/logs/` + `data/archive_manifest.json` | C1, C2 |
| TCA查询回归 | `CostView/.pytest_cache/tca_regression_*.json` | 全局 |
| DB完整性 | `data/backups/*/integrity_*.txt` | 全局 |
| 磁盘/WAL监控 | `scripts/logs/health_*.log` | D1, D3 |

> 验收: 观察期日志连续14天 `all_pass: true` 且无 `blocking_conditions_triggered`。

---

## 协作模式

```
日常操作流程:
  1. 打开本文件 → 看 §一 进度, 确定当前步骤
  2. 点击本文件中该步骤的"执行指南"链接 → 跳转到执行指南对应节
  3. 执行指南中查阅具体实施方案、安全网细节、代码示例
  4. 完成后 → 回到本文件, 将状态从 ⬜ 改为 ✅

修改参数流程:
  1. 修改本节 §二 中的参数值
  2. 执行指南中的受影响步骤会自动关联 (参数表已标注)

审查结果流程:
  1. 打开本节 §三, 找到对应步骤的证据文件路径
  2. 直接打开该文件查看实际校验结果
  3. 对照执行指南 §步骤9 的断言标准判断是否通过
```

两个文件通过**步骤编号**（A1-A8, B1-B4, C1-C2, D1-D3）、**参数名**、**证据文件路径**对齐，形成完整的"控制 → 执行 → 验证"闭环。
