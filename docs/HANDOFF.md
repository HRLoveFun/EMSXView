# DataPipeline Module — Session Handoff

## 当前在做什么

Pipeline 整体可运行。当前已完成两个关键修复：

### 修复 1：BDIB 集成 `raw_bdib_rows=0`（2026-05-13）

`bdib_fetcher.py` 中列名不一致导致 S5（IntegrateBDIBStage）始终跳过数据写入：

| 位置 | 原值 | 修复值 |
|------|------|--------|
| `bdib_fetcher.py:262` (写入) | `df["Order As of Date"] = date_str` | `df["order_as_of_date"] = date_str` |
| `bdib_fetcher.py:409` (检查) | 查 `"order_as_of_date"`（小写蛇形） | — |

列名不匹配 → `fetch_bdib_for_fills()` groupby 条件永远为 False → 返回空 dict → S5 认为无数据可写。
**修复后验证：** `raw_bdib_rows=10,005,601`，`fill_bdib_rows=177,121`。

同时执行了 `fill_bdib` 历史回填：基于已有 raw_bdib 数据，对所有缺失日期重新执行 merge 集成（89 天，2,632,976 行）。`fill_bdib` 覆盖 108 天（2025-09-26 ~ 2026-05-08）。

### 修复 2：raw_fills 空 `order_as_of_date`（2026-05-13）

`upsert_raw_api_data()` 设计上只写入 28 个 EMSX 原始字段（`EMSX_FILL_COLUMNS`），不包含衍生字段 `order_as_of_date`，导致 SQLite 写入 NULL（2,218,512 行）或空字符串（57,339 行）。

| 改动 | 说明 |
|------|------|
| `raw_fills.py:145-152` | `upsert_raw_api_data()` 内对 `DateTimeOfFill` 执行 `derive_exchange_times()` 推导 `order_as_of_date` |
| `raw_fills.py:156` | INSERT 列集新增 `order_as_of_date` |
| 历史回填 | 2,275,851 行 UPDATE 回填（49 个 source_date，2026-03-05 ~ 2026-05-12） |
| 边缘处理 | Exchange=`MUMBAI`（240 行，不在 `EXCHANGE_TIMEZONE` 中）→ 保持 NULL 暴露异常 |

### 当前数据库状态

| 表 | 行数 | 日期范围 |
|------|------|---------|
| `raw_fills` | 8,697,160 | 2025-09-15 ~ 2026-05-12 |
| `processed_fills` | ~9,341,604 | 2025-09-15 ~ 2026-05-12 |
| `raw_bdib` | ~366M | 2025-09-25 ~ 2026-05-08（159 天） |
| `fill_bdib` | 3,478,602 | 2025-09-26 ~ 2026-05-08（108 天） |
| `order_as_of_date` 空值 | 240 行 | Exchange=`MUMBAI` 未映射 |

**当前阻塞项：** 无。所有 pipeline stage 均通过（S5 BDIB 回报 `"completed": true`，`raw_bdib_rows > 0`）。

## 已经试过的方案和结果（含失败的）

### 阶段 1-6：计划性重构（上一 session，全部成功）

| Phase | 内容 | 结果 |
|-------|------|------|
| 1 | 删除 3 个废弃 re-export 桩文件 | ✅ 零引用，干净删除 |
| 2 | 修复 `stages_analysis.py` 跨包相对导入 | ✅ 改为 `from CostView.src.xxx` 绝对路径 |
| 3 | Config 类拆分为 DatabaseConfig / ProcessingConfig / LoggingConfig | ❌ **过度工程**，后合并回单文件 `config.py` |
| 4 | 目录扁平化：`src/` → 根目录，`common/utils/` → `common/` | ✅ 37 个文件迁移 |
| 5 | 添加 `pyproject.toml` | ✅ |
| 6 | 合并 Config 回单文件 | ✅ |

### 运行时 BUG 修复（上一 session，全部成功）

| Bug | 根因 | 修复 |
|-----|------|------|
| H1: `self.raw_db is None` | 迁移 Repository 时守卫条件未更新 | `self.raw_db` → `self.raw_fill_read` |
| H2: `integrated.py` 导入已删除文件 | 惰性导入指向已删除的 `fill_bdib_db.py` | 内联 `STORED_COLUMNS` |
| H3: `market_data.py` 导入已删除文件 | 同上，`processed_raw_bdib_db.py` | 内联 `PROCESSED_RAW_BDIB_COLUMNS` |
| M3: config.py 表名重复 | 模块级 + 类级各定义一次 | 删除模块级常量（22行） |
| H4: ingestion/__init__.py __all__ 导出不存在符号 | 前序迁移残留 | 删除 `FetchHistoryDB` |
| L4: core.py 重复 import | 前序重构残留 | 删除第 142-150 行重复导入 |
| M2: fetch_history_db wrapper | 20 行适配器类 | 删除，`fill_fetch.py` 直连 `SqliteFetchHistoryRepository` |
| M1: facade.py 类名不一致 | `DatabaseFacade` 别名 `CostViewDatabase` | 重命名 `CostViewDatabase` → `DatabaseFacade` |
| M4: DDL 重复 | `_schema.py` 和 `inline_ddl.py` 各自定义 | `inline_ddl.py` 成为单来源 |

### 数据库获取（FillFetch）修复链（上一 session）

| 问题 | 修复 |
|------|------|
| `check_fetch_duplicate` 不存在 | 添加方法到 `SqliteRawFillWriteRepository` |
| `add_fetch_log_record` 不存在 | 添加方法 |
| `upsert_order_fetch_log` 不存在 | 添加方法 |
| `add_fetch_record` 不存在 | 添加方法到 `SqliteFetchHistoryRepository` |
| `compute_derived_fields` 不存在 | 添加方法到 `SqliteMarketDataWriteRepository` |
| `_ensure_schema_context` 不存在 | 添加方法到 `SqliteRegimeWriteRepository` |
| `get_last_fetch_date()` 返回 str | `strptime().date()` 包装 |
| `NOT NULL constraint failed: raw_fills.OrderId` | `FILL_FIELD_EXTRACTORS` getter 方法名修复 |

### BDIB 列名不一致导致 rows=0（本 session，已修复 ✅）

| 位置 | 错误值 | 修复值 |
|------|--------|--------|
| `bdib_fetcher.py:262` | `df["Order As of Date"] = date_str` | `df["order_as_of_date"] = date_str` |

**失败尝试：** `run_bdib_integration(force=True)` → 1 小时超时。原因：强制重跑对所有 180 天重新从 Bloomberg fetch 完整 BDIB 数据（~1700 ticker/天），耗时不可接受。改用按日从本地 `raw_bdib.db` 读取 + 直接集成脚本，89 天在 ~25 分钟内完成。

### raw_fills `order_as_of_date` NULL/空填充（本 session，已修复 ✅）

| 层面 | 改前 | 改后 |
|------|------|------|
| 新数据写入 | `upsert_raw_api_data()` 不写 `order_as_of_date` → NULL | 在 INSERT 前对 `DateTimeOfFill` 执行 `derive_exchange_times()` 推导 |
| 历史回填 | 2,275,851 行 NULL/空 | `derive_exchange_times()` 逐 source_date 回填 |
| 异常保留 | — | Exchange 不在时区映射表 → 保持 NULL（240 行 `MUMBAI`） |

## 下一步计划（3-5条 actionable）


1. **统一 raw_fills 的 `order_as_of_date` 格式**——当前混合两种格式：
   - Excel 导入行（6,390,388 行）：`YYYY-MM-DD HH:MM:SS`（如 `2025-09-15 00:00:00`）
   - API fetch + 回填行（~2,275,851 行）：`YYYYMMDD`（如 `20260512`）
   Pipeline 的 `get_fills_for_date()` 先按 `order_as_of_date=?` 查，若为空会 fallback 到 `source_date`。格式不统一可能导致部分按 `order_as_of_date` 的查询漏掉旧格式行。建议统一清洗：
   ```sql
   UPDATE raw_fills SET order_as_of_date = REPLACE(SUBSTR(order_as_of_date, 1, 10), '-', '')
   WHERE order_as_of_date LIKE '____-__-__%';
   ```

2. **验证 `RouteId` merge 类型修复（commit `055e0db`）**——部署后重新触发 pipeline，观察 Stage 2 是否仍报 `int64 vs object` 类型错误。参见上一 session 的 `numeric_cols` 修改 (`fill_cleaner.py:227-230`)。

3. **部署所有 commit，重启后端，点击 Trigger Update，观察 pipeline 全链路是否完整跑通**——重点关注：
   - Stage S2 (Process Raw Fills)：`upsert_processed_fills` 写入正常
   - Stage S5 (BDIB Integration)：`raw_bdib_rows > 0`
   - Stage S7 (Daily Metrics)：`rows > 0`
   - 前端 database 模块统计信息的 "Updated" 时间戳

4. **处理 `CostView/src/query_cli.py:31` 引用已删除的 `RawFillsDB`**——该文件导入会崩溃（`from .raw_fills_db import RawFillsDB`），当前不在 pipeline 路径中，但若有人使用 CLI 工具会报错。改为使用 `SqliteRawFillReadRepository`。

## 关键文件路径（相对路径，一行一个）

```
# 本 session 改动的文件
DataPipeline/acquisition/bdib_fetcher.py              — line 262: "Order As of Date" → "order_as_of_date"
DataPipeline/storage/repositories/raw_fills.py         — upsert_raw_api_data() 新增 derive_exchange_times() 推导 oaod

# 上一 session 改动的文件（仍相关）
DataPipeline/acquisition/_constants.py                 — FILL_FIELD_EXTRACTORS getter 方法名修复
DataPipeline/acquisition/bloomberg_fill_fetcher.py      — _parse_fill_messages 修复 Fills 数组解析
DataPipeline/ingestion/fill_fetch.py                   — FillFetch 主流程
DataPipeline/ingestion/fill_ingestion.py               — process_raw_fills_for_date，修复 upsert_processed_fills 传参
DataPipeline/processing/fill_cleaner.py                — numeric_cols（RouteId/FillId 不再转 numeric）
DataPipeline/storage/repositories/fills.py             — upsert_execution_history 等方法
DataPipeline/storage/repositories/market_data.py       — compute_derived_fields
DataPipeline/storage/repositories/regime.py            — _ensure_schema_context
DataPipeline/storage/repositories/fetch_history.py     — add_fetch_record
DataPipeline/common/exchange_tz.py                     — EXCHANGE_TIMEZONE 时区映射表
DataPipeline/storage/schema/inline_ddl.py              — DDL 定义
docs/api/emsx-api-guide.md                             — Bloomberg EMSX API 文档

# 临时脚本（已删除，参考用）
Temp\opencode\backfill_fill_bdib.py                    — fill_bdib 回填（89 天）
Temp\opencode\backfill_raw_fills_oaod.py               — raw_fills order_as_of_date 回填（49 天）
```

## 还没搞清楚的问题

1. **raw_fills 格式不一致的查询影响**——现有 6,390,388 行 `order_as_of_date` 是 `YYYY-MM-DD HH:MM:SS` 格式，而 pipeline 查询用 `YYYYMMDD` 参数与 TEXT 字段比较。SQLite 是字符串比较，`"2025-09-15 00:00:00" != "20250915"`。当前 `get_fills_for_date()` 有 `source_date` fallback 才勉强可用。统一格式（下一步计划 2）是否会影响任何下游调用？

2. **`RouteId` merge 类型修复是否完整**——commit `055e0db` 从 `numeric_cols` 删除了 `RouteId` 和 `FillId`，但 `fill_cleaner.py` 中其他位置是否还有对 `RouteId` 做 `pd.to_numeric()` 的调用？建议 grep 确认。

3. **xbbg `"too close to current time"` 保护机制**——BDIB fetch 时 xbbg 内部拒绝查询昨日数据（返回 `Intraday Bar Error: NOT_AVAILABLE`），导致增量运行时最新 1-2 天无 BDIB 数据。这是 xbbg 的行为，非代码 bug。但如果用户需要在当天收盘后尽早看到 BDIB 数据，可考虑将每日 pipeline 触发时间推迟到凌晨（xbbg 通常在次日 UTC 凌晨解锁昨日数据）。

4. **`CostView/tests/test_pipeline_stages.py` 的 `@patch` 路径错误**——测试模块名是 `stages_ingest` 不是 `stages`。这些测试从未正确工作过。是否要修复或标记为预期失败？
