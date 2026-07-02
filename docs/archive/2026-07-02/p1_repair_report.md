# P1 修复实施报告 — raw_fills 空字段 + oaod NOT NULL

> 实施日期：2026-07-02
> 实施人：CodeBuddy + hrchen
> 修复对象：exchange_exec_time + order_as_of_date 字段

---

## 一、问题概述

### 问题 1：exchange_exec_time NULL（代码 bug）

- **影响**：4,667,570 行 (41.69%) `exchange_exec_time` 为 NULL
- **根因**：`upsert_raw_api_data`（`raw_fills.py` L207）写入 cols 列表遗漏了
  `exchange_exec_time` 字段（该字段在 `DERIVED_COLUMNS` 中，不在 `EMSX_FILL_COLUMNS` 中）

### 问题 2：order_as_of_date NULL（历史数据损坏）

- **影响**：240 行 (0.002%) `order_as_of_date` 为 NULL
- **范围**：5 个 OrderId × 5 个交易日 = 240 行，全部 MUMBAI 交易所
- **根因**：`EXCHANGE_TIMEZONE` 字典未含 `MUMBAI`（Bloomberg EMSX 对 NSE 印度订单
  返回 `Exchange='MUMBAI'`，而原字典只含 `IN`/`IS`/`IB`），4/7 16:24-16:26 scope 切换
  重写时 MUMBAI 行的 oaod/eet 派生失败，写入 NULL

---

## 二、修复实施

### 步骤 1：代码修复

| 文件 | 修复内容 |
|------|----------|
| `DataPipeline/common/exchange_tz.py` | `EXCHANGE_TIMEZONE` 添加 `MUMBAI`/`BSE`/`NSE` → `Asia/Calcutta` |
| `DataPipeline/common/exchange_tz.py` | `batch_convert_ny_to_local` 加 mixed-tz 兜底（防 .dt.tz AttributeError） |
| `DataPipeline/storage/repositories/raw_fills.py` | `upsert_raw_api_data` cols 添加 `exchange_exec_time` 字段 |
| `DataPipeline/storage/schema/migration_framework.py` | `_EXPECTED_CURRENT["raw_fills"]` 3 → 4 |

### 步骤 2：迁移文件创建

- 新文件 `DataPipeline/storage/schema/migrations/raw_fills/v3_to_v4.sql`
- 重建表 + `order_as_of_date TEXT NOT NULL DEFAULT ''`

### 步骤 3：数据回填

- 新脚本 `scripts/ops/backfill_raw_fills_oaod_eet.py`
- 处理 4,667,570 行 UPDATE
- 速率：dry-run 60k 行/秒；execute 21k 行/秒
- 耗时：226 秒
- 结果：oaod_null 240→0, eet_null 4,667,570→0

### 步骤 4：执行 migration

- 新脚本 `scripts/ops/apply_v3_to_v4.py`
- 前置校验 + 执行 migration + 验收
- 耗时：93.6 秒（7.5GB 表重建）

### 步骤 5：单元测试

- 新测试 `DataPipeline/tests/storage/test_raw_fills_oaod_notnull.py`
- 12 个测试用例覆盖：tz 映射、derive 计算、upsert cols、表约束、DB 状态
- **12/12 PASS**

---

## 三、最终验收

### 数据状态

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| oaod NULL/空串 | 240 | **0** |
| eet NULL/空串 | 4,667,570 | **0** |
| user_version | 3 | **4** |
| oaod NOT NULL 约束 | 无 | **有** |
| total rows | 11,057,958 | 11,057,958 |

### 测试结果

```
TestExchangeTimezoneMapping::test_mumbai_mapped            PASSED
TestExchangeTimezoneMapping::test_bse_mapped               PASSED
TestExchangeTimezoneMapping::test_nse_mapped               PASSED
TestExchangeTimezoneMapping::test_legacy_india_codes_intact PASSED
TestMumbaiDeriveExchangeTimes::test_mumbai_oaod_from_ny_dt PASSED
TestMumbaiDeriveExchangeTimes::test_mumbai_eet_format      PASSED
TestMumbaiDeriveExchangeTimes::test_mixed_exchanges_robustness PASSED
TestUpsertRawApiDataSchema::test_cols_includes_exchange_exec_time PASSED
TestUpsertRawApiDataSchema::test_cols_includes_order_as_of_date PASSED
TestRawFillsSchemaConstraints::test_oaod_notnull_constraint PASSED
TestRawFillsSchemaConstraints::test_user_version_is_v4     PASSED
TestRawFillsSchemaConstraints::test_no_null_oaod_rows      PASSED

12 passed, 6 warnings in 1.25s
```

---

## 四、产出文件清单

| 类型 | 文件 |
|------|------|
| 代码修复 | `DataPipeline/common/exchange_tz.py` |
| 代码修复 | `DataPipeline/storage/repositories/raw_fills.py` |
| 代码修复 | `DataPipeline/storage/schema/migration_framework.py` |
| Migration | `DataPipeline/storage/schema/migrations/raw_fills/v3_to_v4.sql` |
| 回填脚本 | `scripts/ops/backfill_raw_fills_oaod_eet.py` |
| 迁移脚本 | `scripts/ops/apply_v3_to_v4.py` |
| 单元测试 | `DataPipeline/tests/storage/test_raw_fills_oaod_notnull.py` |
| 调查文档 | `docs/spec/raw_fills_null_investigation.md` |
| 实施报告 | `docs/spec/p1_repair_report.md`（本文） |

---

## 五、风险与回滚

### 风险

1. **回填期间 DB 锁**：UPDATE 期间其他写入阻塞
2. **migration 期间 DB 不可用**：7.5GB 表重建需 ~90s
3. **混合 tz 数据**：mixed-tz 修复覆盖兜底，不影响正确性

### 回滚

1. 备份：`CostView/data/raw_fills.db.bak_20260702` (7.49 GB)
2. 回滚 SQL：从 v3_to_v4.sql 反向（`order_as_of_date TEXT DEFAULT ''`，无 NOT NULL）
3. 回滚代码：`git revert` 4 个代码修复

---

## 六、后续建议

1. **EXCHANGE_TIMEZONE 字典审计**：定期对账 Bloomberg 实际 Exchange code 与字典，
   避免再次出现 MUMBAI 类遗漏
2. **添加 NOT NULL 约束检查**：在迁移框架的 precheck 阶段增加对所有 NOT NULL 字段
   的 NULL 数校验
3. **fetch_log 增强（已记录的 P2）**：添加 `scope` 列记录 TradingSystem/Team
