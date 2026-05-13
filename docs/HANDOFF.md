# DataPipeline Module — Session Handoff

## 当前在做什么

DataPipeline 模块大规模重构已基本完成。当前处于**修复阶段 B（processing pipeline）的最后一个报错**的状态。Pipeline 整体可运行但 S2 processing 有 `RouteId` merge 类型错误的遗留问题。

**当前阻塞项：** `fill_processor.py` 中 `clean_emsx_fills` 将 `RouteId` 转为 numeric → processing 阶段 merge `RouteId` 时报 `int64 vs object` 类型不匹配。修复方案：

```python
# fill_cleaner.py:227-230 — 已执行
numeric_cols = [
    "OrderId", "Amount", "LimitPrice", "StopPrice", "TraderUuid",
    # "RouteId" ← 已删除
    "RouteShares",
    # "FillId"  ← 已删除
    "FillPrice", "FillShares",
]
```

该改动已提交（commit `055e0db`），但**需要在部署后重新触发一次 pipeline 验证**。

## 已经试过的方案和结果（含失败的）

### 阶段 1-6：计划性重构（全部成功）

| Phase | 内容 | 结果 |
|-------|------|------|
| 1 | 删除 3 个废弃 re-export 桩文件 | ✅ 零引用，干净删除 |
| 2 | 修复 `stages_analysis.py` 跨包相对导入 | ✅ 改为 `from CostView.src.xxx` 绝对路径 |
| 3 | Config 类拆分为 DatabaseConfig / ProcessingConfig / LoggingConfig | ❌ **过度工程**，后合并回单文件 `config.py` |
| 4 | 目录扁平化：`src/` → 根目录，`common/utils/` → `common/` | ✅ 37 个文件迁移 |
| 5 | 添加 `pyproject.toml` | ✅ |
| 6 | 合并 Config 回单文件 | ✅ |

### 运行时 BUG 修复（全部成功）

| Bug | 根因 | 修复 |
|-----|------|------|
| H1: `self.raw_db is None` | 迁移 Repository 时守卫条件未更新 | `self.raw_db` → `self.raw_fill_read` |
| H2: `integrated.py` 导入已删除文件 | 惰性导入指向已删除的 `fill_bdib_db.py` | 内联 `STORED_COLUMNS` |
| H3: `market_data.py` 导入已删除文件 | 同上，`processed_raw_bdib_db.py` | 内联 `PROCESSED_RAW_BDIB_COLUMNS` |
| M3: config.py 表名重复 | 模块级 + 类级各定义一次 | 删除模块级常量（22行） |
| H4: ingestion/__init__.py __all__ 导出不存在符号 | 前序迁移残留 | 删除 `FetchHistoryDB` |
| L4: core.py 重复 import | 前序重构残留 | 删除第 142-150 行重复导入 |
| M2: fetch_history_db wrapper | 20 行适配器类 | 删除，`fill_fetch.py` 直连 `SqliteFetchHistoryRepository` |
| M1: facade.py 类名不一致 | `DatabaseFacade` 别名 `CostViewDatabase` | 重命名 `DatabaseFacade` → `CostViewDatabase` |
| M4: DDL 重复 | `_schema.py` 和 `inline_ddl.py` 各自定义 `init_processed_fills_schema` | `inline_ddl.py` 成为单来源，`_schema.py` 委派 + 增量 |

### 数据库获取（FillFetch）修复链

| 问题 | 修复 | 阶段 |
|------|------|------|
| `check_fetch_duplicate` 不存在 | 添加方法到 `SqliteRawFillWriteRepository` | P0 |
| `add_fetch_log_record` 不存在 | 添加方法 | P0 |
| `upsert_order_fetch_log` 不存在 | 添加方法 | P0 |
| `add_fetch_record` 不存在 | 添加方法到 `SqliteFetchHistoryRepository` | P0 |
| `compute_derived_fields` 不存在 | 添加方法到 `SqliteMarketDataWriteRepository` | P1 |
| `_ensure_schema_context` 不存在 | 添加方法到 `SqliteRegimeWriteRepository` | P2 |
| `get_last_fetch_date()` 返回 str vs 调用方期望 date | `strptime().date()` 包装 | 第 8 轮 |
| `max(str, date)` TypeError | 同上 | 第 8 轮 |
| **`NOT NULL constraint failed: raw_fills.OrderId`** — OrderId 为 None | 见下 | 核心 bug |

### OrderId 提取失败的根因（关键）

`FILL_FIELD_EXTRACTORS` 中所有 getter 方法名都错了：

| 问题 | 错误值 | 修复值 |
|------|--------|--------|
| `getValueAsString` → `Message` 对象没有此方法 | 全部 28 个字段 | `getElementAsString` |
| `getValueAsInteger` → `Message` 对象没有此方法 | `OrderId`, `RouteId`, `FillId` 等 | `getElementAsInteger` |
| `getValueAsFloat` → `Message` 对象没有此方法 | `Amount`, `FillPrice` 等 | `getElementAsFloat` |
| `GetValueAsFloat`（大小写笔误） | `StopPrice` | `getElementAsFloat` |

确认于 `docs/api/emsx-api-guide.md` line 5335-5404。

### GetFillsResponse 消息结构（第 2 个关键 bug）

```python
# 错误：把消息当扁平 dict 解析
def _parse_fill_message(msg):
    fill[field] = msg.getValueAsString(field)  # ❌

# 正确：消息有 Fills 数组
def _parse_fill_messages(msg):
    fills_el = msg.getElement("Fills")
    for i in range(fills_el.numValues()):
        fill_el = fills_el.getValueAsElement(i)
        fill[field] = fill_el.getElementAsString(field)  # ✅
```

### 上一个 session 遗留的报错

`upsert_processed_fills(processed, date_str)` — 第二个位置参数 `date_str` 被传给了 `conn` 参数 → `'str' object has no attribute 'executemany'`。已修复为 `upsert_processed_fills(processed)`。

## 下一步计划（3-5条 actionable）

1. **部署所有 commit，重启后端，点击 Trigger Update，观察日志确认 Stage B 完整跑通**。关注 Stage 2 (Process Raw Fills) 的 `upsert_processed_fills` 是否成功写入 processed_fills.db。

2. **验证前端 database 模块的统计信息是否正常显示**——检查 raw_fills 和 processed_fills 的 "Updated" 时间戳是否刷新到最新。

3. **修复 `fill_cleaner.py:227-230` 中 RouteId/FillId 不再转 numeric 后的数据一致性**——commit `055e0db` 已提交，但部署后才能验证效果。观察 `_build_execution_history_frames` 的 merge 是否不再报类型错误。

4. **处理 `CostView/src/query_cli.py:31` 引用已删除的 `RawFillsDB`**—该文件目前的 import 会崩溃（`from .raw_fills_db import RawFillsDB`），但当前不在 pipeline 路径中。如果需要修复，改为使用 `SqliteRawFillReadRepository`。

5. **清理临时调试文件**：`C:\Users\hrchen\AppData\Local\Temp\opencode\check_data.py`、`check_data2.py`。

## 关键文件路径（相对路径，一行一个）

```
# 最近改动的文件
DataPipeline/acquisition/_constants.py             — FILL_FIELD_EXTRACTORS 定义，修复 getter 方法名
DataPipeline/acquisition/bloomberg_fill_fetcher.py  — _parse_fill_messages，修复 Fills 数组解析
DataPipeline/ingestion/fill_fetch.py                — FillFetch 主流程，H1 修复 + 方法补全
DataPipeline/ingestion/fill_ingestion.py            — process_raw_fills_for_date，修复 upsert_processed_fills 传参
DataPipeline/processing/fill_cleaner.py             — numeric_cols，RouteId/FillId 不再转 numeric
DataPipeline/storage/repositories/raw_fills.py      — 添加 add_fetch_log_record / check_fetch_duplicate 等方法
DataPipeline/storage/repositories/fills.py          — 添加 upsert_execution_history / get_route_registry_for_date 等方法
DataPipeline/storage/repositories/market_data.py    — 添加 compute_derived_fields
DataPipeline/storage/repositories/regime.py         — 添加 _ensure_schema_context
DataPipeline/storage/repositories/fetch_history.py  — 添加 add_fetch_record
DataPipeline/storage/connection.py                  — 修复 import（删除已废弃模块引用）
DataPipeline/storage/facade.py                      — DatabaseFacade → CostViewDatabase 重命名
DataPipeline/storage/schema/inline_ddl.py           — DDL 单来源，补齐缺失表
DataPipeline/storage/repositories/_schema.py        — 委派 inline_ddl + 增量逻辑
DataPipeline/config.py                              — 合并后单文件配置
DataPipeline/pyproject.toml                         — 包定义
platform_data/repositories.py                       — 修复 import（模块级常量→Config 类）
platform_data/database_diagnostics.py               — 同上
CostView/scripts/daily_update.py                    — DB state 日志（添加 mtime 记录）
docs/api/emsx-api-guide.md                          — Bloomberg EMSX API 文档（确认了 getElement* 的正确用法）
```

## 还没搞清楚的问题

1. **`upsert_processed_fills(processed)` 去掉 `date_str` 后，`_upsert` 是否需要 `date_str`？** ——从代码看 `_upsert` 只接收 `(df, table, key_columns, expected_columns, conn)`，不接收 `date_str`。但在 `process_raw_fills_for_date` 中，如果 `upsert_processed_fills` 不需要 `date_str`，那么 upsert 到 processed_fills 表的数据里是否缺少某个日期字段？需要验证 `upsert_processed_fills` 使用 `_upsert`，该方法通过 `key_columns` 匹配更新行，不依赖 `date_str`。如果 processed_fills 表中有 `order_as_of_date` 字段，它在 `PROCESSED_COLUMNS` 列表里，由 `processed` DataFrame 提供。所以 `date_str` 对 `upsert_processed_fills` 是多余的。

2. **Stage S5 (BDIB integration) 的 `raw_bdib_rows=0` 和 `processed_raw_bdib_rows=0`、`fill_bdib_rows=0`** — 可能意味着 BDIB 市场数据 fetch 为空。日志中有 `fetch_bdib_for_fills: 0 ticker-dates fetched` 的大量记录。这可能是因为 xbbg Bloomberg 连接在 BDIB fetch 时不可用。需要确认是否是 Bloomberg 终端权限问题。

3. **Stage S7 (CalculateDailyMetrics) `rows=3065, dates=8`** — 这 8 天是从哪里来的？可能是从之前的旧数据中计算得出的。这部分是否随着新 raw_fills 数据的增加而更新，需要通过 pipeline 验证。

4. **`CostView/src/query_cli.py`** — 导入已删除的 `RawFillsDB`，当前不在 pipeline 路径中，但如果有用户使用该 CLI 工具会崩溃。是否要修复？

5. **`CostView/tests/test_pipeline_stages.py` 的 `@patch("DataPipeline.orchestration.stages.xxx")` 路径错误** — 测试模块名是 `stages_ingest` 不是 `stages`。这些测试从未正确工作过。是否要修复或标记为预期失败？
