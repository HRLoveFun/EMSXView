# S1 Process Raw Fills — 下游兼容矩阵

> 适用版本：`branch = 001-architecture-module-completion`  
> 范围：S1 阶段 4 张表（`raw_fills` / `processed_fills` / `route_registry` / `route_history` / `route_event_history`）的字段改动，盘点下游消费方。  
> 关联：[S1 数据修复方案 v2](../../AppData/Roaming/CodeBuddy%20CN/User/globalStorage/tencent-cloud.coding-copilot/plans/77b90209e4314c1583cc619fe3123e24/plan.md)

---

## 1. 改动字段清单

| 表 | 字段 | 改动 | 风险等级 |
| --- | --- | --- | --- |
| `raw_fills` | `LimitPrice` / `StopPrice` | `TEXT` → `REAL`；缺失保持 `NULL` | 低（SQLite 数字亲和） |
| `raw_fills` | `order_as_of_time` / `route_as_of_time` / `local_fill_datetime` | 停止写入（标记 deprecated） | 中（测试 fixture 仍创建） |
| `raw_fills` | `ingested_at` | 暂保留；停止新增 | 低 |
| `raw_fills` | `exchange_exec_time` / `order_as_of_date` | 停止写入（标记 deprecated） | 低 |
| `processed_fills` | `equ_ticker` | 空 `Exchange` 或空 `Ticker` 时输出 `None` | 低（数据语义更严） |
| `route_registry` | `count_fill` / `count_broker` / `count_algo` / `count_trader` | S1 groupby 计算并 assign | 低（新增列，从 `NULL` → 有值） |
| `route_history` | `equ_ticker` / `ccy_ticker` / `Side` | 来源从 `route_registry` 二次 merge 改为 `processed` 自身 | **中**（高频 JOIN key，必须保留） |
| `route_history` | `first_fill_time` / `last_fill_time` | 字符串比较 → `pd.to_datetime().min()/.max()`，统一用 `local_fill_datetime` | 低（输出格式一致） |
| `route_event_history` | `equ_ticker` / `ccy_ticker` / `Side` | 与 `route_history` 同源修复 | 低 |
| `route_event_history` | `source_refreshed_at` | `datetime.utcnow()` → `datetime.now(timezone.utc)`（带 `+00:00`） | **零下游消费者**，低 |
| `route_event_history` | `event_timestamp` | 统一用 `local_fill_datetime`（移除 `DateTimeOfFill` 兜底） | 低 |
| `processed_fills` (写入层) | `key_columns` | `["FillId"]` → `["OrderId", "RouteId", "FillId", "order_as_of_date"]` | **零**（当前 `_upsert_fixed_schema` 未实际使用 `key_columns`） |

---

## 2. 字段逐项下游审计

### 2.1 `LimitPrice` / `StopPrice`

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| Bloomberg EMSX 拉取 | `DataPipeline/acquisition/_constants.py:65-66` | 写入 | 已用 `getElementAsFloat`，异常→`None` |
| Cleaner normalize | `DataPipeline/processing/fill_cleaner.py:226-232` | 写入 | `pd.to_numeric(errors="coerce")` 对 TEXT/REAL 同样有效 |
| Inline DDL | `DataPipeline/storage/schema/inline_ddl.py:60, 62` | 写入 | 当前 `TEXT`，需改 `REAL` |
| Inline DDL fixture | `DataPipeline/tests/guardrail/conftest.py` | 写入 | 需确认 fixture 同步 |
| Legacy Excel DDL | `scripts/ops/import_excel_fills.py:818, 820` | 写入 | **legacy deprecated**，仍保留以兼容历史 Excel 导入 |
| 测试 fixture | `CostView/tests/test_tca_query_service.py:198-199` | 写入 | 需同步改 `REAL` |
| Bloomberg adapter (订单对象) | `backend/api/schemas/orders.py` 等 9 处 | 读取 | 与 raw_fills 库**无关**（EMSX 订单对象 schema） |
| 前端表单 | `frontend/src/modules/execution/components/modify-limit-price-dialog.tsx` 等 8 处 | 读取 | 与 raw_fills 库**无关**（订单操作 UI） |

**结论**：raw_fills 库内消费仅 5 处需同步（3 处 DDL/写入，1 处 normalize，1 处 fixture），全部安全。

### 2.2 `order_as_of_time` / `route_as_of_time` / `local_fill_datetime` / `exchange_exec_time` / `order_as_of_date`

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| Fetcher 写入 | `DataPipeline/ingestion/fill_ingestion.py` 路径 | **未写入** raw_fills | 仅在 `processed` DataFrame 中派生 |
| Inline DDL | `DataPipeline/storage/schema/inline_ddl.py:81-82, 84-85` | 创建列 | 需加 deprecated 注释 |
| Tests fixture | `CostView/tests/test_tca_query_service.py:205-207` | 创建列 | 需保留以兼容测试 |
| Cleaner derive | `DataPipeline/processing/fill_cleaner.py:174-198` | 派生写入 processed | 与 raw_fills 解耦 |
| API schemas | `backend/api/schemas/history.py:58-59, 89-90` | 读取 | 读取 `first_fill_time`/`last_fill_time`，不是 raw_fills 这 5 列 |
| Diagnose scripts | `scripts/diagnose/diagnose_orders_display.py`, `scripts/devtools/fetch_and_inspect.py` | 读取 | 需确认是否依赖 |
| Order label | `DataPipeline/processing/order_label.py` | 读取 | 需确认 |

**结论**：raw_fills 库内仅 DDL 创建处和测试 fixture 需同步。下游消费者以 `processed_fills` 派生列为主。

### 2.3 `ingested_at`

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| Inline DDL | `DataPipeline/storage/schema/inline_ddl.py:80` | DEFAULT `datetime('now')` | 与 `fetched_at` 重复 |
| Raw fills repo | `DataPipeline/storage/repositories/raw_fills.py:262` | `all_columns` 列表 | 写入列名 |
| Storage DTO | `DataPipeline/storage/dto.py` | 字段定义 | 需确认 |
| 全部 storage migrations | `DataPipeline/storage/schema/migrations/*.sql` | 历史列 | 保留 |
| Regime storage | `DataPipeline/storage/repositories/regime.py`, `DataPipeline/analysis/regime/*.py` | 字段引用 | 需确认 |

**结论**：`ingested_at` 与 `fetched_at` 重复，v2 方案决定**暂保留**（避免破坏性），下版本移除。

### 2.4 `equ_ticker` / `ccy_ticker` / `Side`（route_history / route_event_history）

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| `tca_query_builder.get_matching_routes` | `CostView/src/tca_query_builder.py:129, 146-148` | 读取 | 直接 `rh.equ_ticker / rh.ccy_ticker / rh.Side` |
| `tca_query_builder.get_route_summary` | `CostView/src/tca_query_builder.py:183-185` | 读取 | `rr.equ_ticker / rr.ccy_ticker / rr.Side` |
| `tca_query_builder.get_route_summary` | `CostView/src/tca_query_builder.py:195, 217` | 读取 | `COALESCE(rh.equ_ticker, oh.equ_ticker)` |
| `execution_history_service.list_fill_history` | `platform_data/execution_history_service.py:85-87` | 读取 | `rr.Side / rr.equ_ticker / rr.ccy_ticker` |
| `execution_history_service.list_order_summary` | `platform_data/execution_history_service.py:147-148` | 读取 | `MAX(rr.equ_ticker) / MAX(rr.Side)` |
| `execution_history_service.list_route_summary` | `platform_data/execution_history_service.py:216-217` | 读取 | `MAX(rr.Side) / MAX(rr.equ_ticker)` |
| `CostView/api/routers/costview.py:487, 509` | 读取 | `o.equ_ticker / r.side` | 间接通过 `tca_query_service` |
| Inline DDL (route_registry) | `DataPipeline/storage/schema/inline_ddl.py:301-308` | 写入 | 与 `columns.py` 对齐 |
| Inline DDL (route_history VIEW) | `DataPipeline/storage/schema/inline_ddl.py:321-351` | VIEW 定义 | `order_history` VIEW 派生 `MAX(equ_ticker)` |
| `db_partition.sql:16-31, 67-86` | 写入 DDL | **与 columns.py 不一致**（用 `EquTicker/Broker/Algo/Currency/Amount/total_fills`） | 需对齐 |
| `_build_execution_history_frames` | `DataPipeline/ingestion/fill_ingestion.py:80-164` | 写入 | **当前依赖 `route_reg_df` 二次 merge → 改为从 `processed` 直接取** |

**结论**：高频 JOIN key，**必须保留**。修复点：`_build_execution_history_frames` 改为从 `processed_df.itertuples` 直接取。

### 2.5 `first_fill_time` / `last_fill_time`

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| `tca_query_builder.get_matching_routes` | `CostView/src/tca_query_builder.py:153-156, 169` | 读取 | 字符串 `substr(...)` 截取 + `ORDER BY` |
| `execution_history_service.list_order_summary` | `platform_data/execution_history_service.py:156-157, 165` | 读取 | SQLite SQL `MIN/MAX(COALESCE(...))` |
| `execution_history_service.list_route_summary` | `platform_data/execution_history_service.py:224-225, 233` | 读取 | 同上 |
| API schemas | `backend/api/schemas/history.py:58-59, 89-90` | 字段定义 | `Optional[str]` |
| Bloomberg adapter | `backend/api/services/bloomberg/subscriptions.py, _constants.py` | 字段定义 | 与本表无关 |
| Inline DDL | `DataPipeline/storage/schema/inline_ddl.py` (route_history) | 写入 | 已声明 |
| `_first_last_event_time` | `DataPipeline/ingestion/fill_ingestion.py:63-78` | 写入 | **当前用字符串 `min/max`**，需修 |

**结论**：消费者都用 `local_fill_datetime` 派生列作 `COALESCE` 兜底，**统一用 `local_fill_datetime`** 不会破坏外部 API。

### 2.6 `source_refreshed_at`

| 消费者 | 文件:行 | 读/写 | 备注 |
| --- | --- | --- | --- |
| Inline DDL | `DataPipeline/storage/schema/inline_ddl.py` | 写入 | 已有 `source_refreshed_at` |
| `db_partition.sql` | 多个表 | DEFAULT `datetime('now')` | 需同步改 UTC |
| `_build_execution_history_frames` | `DataPipeline/ingestion/fill_ingestion.py:87, 119, 155` | 写入 | `datetime.utcnow().isoformat(timespec="seconds")` |
| `columns.py` | `EXECUTION_HISTORY_SOURCE_COLUMNS` | 字段定义 | 已声明 |

**结论**：**零外部消费者**（无 frontend / backend router / costview router 读取），改 UTC 安全。

### 2.7 `ingested_at` 完整下游

- `DataPipeline/storage/schema/migrations/*.sql` — 历史迁移脚本保留
- `DataPipeline/storage/repositories/raw_fills.py:262` — `all_columns = ALL_RAW_COLUMNS + ["source_date", "ingested_at"]`
- `DataPipeline/storage/dto.py` — 字段定义
- `DataPipeline/analysis/regime/*.py` — 5 处 regime storage 使用 `ingested_at`（**与 raw_fills 无关**，是 regime 表的字段）
- `DataPipeline/analysis/attribution/writer.py / repositories.py` — attribution 表的 `ingested_at`（**与 raw_fills 无关**）
- `CostView/tests/test_repository_regime.py` — regime 表测试（与 raw_fills 无关）
- `CostView/tests/test_tca_query_service.py:208` — raw_fills fixture 创建 `ingested_at` 列
- `CostView/tests/testing_helpers.py` — 测试 helper 引用

**结论**：`ingested_at` 在 raw_fills 中无外部消费者，但创建列被 fixture 引用 → 保留列，下版本移除。

---

## 3. 改动兼容矩阵

| 改动 | 内部影响 | 外部 API 影响 | 修复复杂度 |
| --- | --- | --- | --- |
| `LimitPrice/StopPrice TEXT→REAL` | 3 处 DDL/写入 + 1 处 fixture | 无 | 低 |
| 5 个 raw_fills 派生列停写 | 1 处 DDL 注释 + 1 处 fixture | 无 | 低 |
| `processed_fills.equ_ticker` 改 None 策略 | `add_equity_ticker` 1 处 | 无（语义更严） | 低 |
| `route_registry` 4 count 列 | `process_raw_fills_for_date` 1 处 | 无（NULL→有值） | 低 |
| `route_history` 等改 `processed` 来源 | `_build_execution_history_frames` 1 处 | 无（输出更准） | 中 |
| `first_fill_time/last_fill_time` 改 pd.to_datetime | `_first_last_event_time` 1 处 | 无（输出格式不变） | 低 |
| `source_refreshed_at` 改 UTC | `_build_execution_history_frames` 1 处 | 无（**零外部消费者**） | 低 |
| `key_columns` 4 元组 | `upsert_processed_fills` 1 处 | 无（实际未使用） | 低 |

---

## 4. 必须同步的 fixture / 脚本清单

| 文件:行 | 现状 | 需同步 |
| --- | --- | --- |
| `CostView/tests/test_tca_query_service.py:198-208` | `LimitPrice TEXT, StopPrice TEXT, ... order_as_of_time TEXT, exchange_exec_time TEXT, route_as_of_time TEXT, local_fill_datetime TEXT, ingested_at TEXT` | `LimitPrice REAL, StopPrice REAL, ...` 其余保留 |
| `scripts/ops/import_excel_fills.py:818-841` | legacy DDL 同步 | `LimitPrice/StopPrice TEXT → REAL`，其余保留 deprecated 注释 |
| `DataPipeline/storage/schema/inline_ddl.py:46-138` | `init_raw_fills_schema` 创建 5 个派生列 | 加 deprecated 注释，类型 `TEXT → REAL` |
| `DataPipeline/storage/schema/db_partition.sql` | route_registry/route_history DDL 与 columns.py 不一致 | 加 deprecated 注释 + 列对齐 |

---

## 5. 风险评估

- **破坏性**：所有改动都向后兼容（保留列/字段、只改类型/逻辑、不删列）
- **数据完整性**：修复后 `equ_ticker` / `count_*` / `first_fill_time` 等字段会从 `NULL` → 正确值，**不会丢失历史数据**（`INSERT OR REPLACE` 自然刷新）
- **类型迁移**：`TEXT → REAL` 在 SQLite 文本亲和下安全（`CAST AS REAL` 自动转换）
- **时区语义**：当前混用 `local_fill_datetime`（无 tz）与 `DateTimeOfFill`（NY tz 有 tz 后缀），改为统一用 `local_fill_datetime` **不会破坏**当前 SQLite 字符串比较（两者都是 `YYYY-MM-DD HH:MM:SS` 形式，但 NY tz 字符串可能含 `+offset`）

---

## 6. 验证步骤

1. **同步 fixture**：`CostView/tests/test_tca_query_service.py::test_tca_query_service` 运行通过
2. **重跑 S1 单日（20260416）**：
   - 抽样 `route_registry`：`count_fill / count_broker / count_algo / count_trader` 100% 命中
   - 抽样 `route_history`：`equ_ticker / ccy_ticker / Side` 100% 命中
   - 抽样 `route_event_history`：`equ_ticker / ccy_ticker / Side / source_refreshed_at` 100% 命中
   - 抽样 `processed_fills.equ_ticker`：空 Exchange/Ticker 行输出 `None`，其他行非空
3. **回归测试**：`pytest CostView/tests/test_tca_query_service.py backend/api/tests/ DataPipeline/tests/`

---

## 7. 引用

- v2 方案：`%APPDATA%\CodeBuddy CN\User\globalStorage\tencent-cloud.coding-copilot\plans\77b90209e4314c1583cc619fe3123e24\plan.md`
- 业务流程：`DataPipeline/BUSINESS_FLOW.md §3`
- 列定义：`DataPipeline/storage/schema/columns.py`
- 仓库写入：`DataPipeline/storage/repositories/fills.py`
- 历史路径解耦：`DataPipeline/ingestion/fill_ingestion.py::_build_execution_history_frames`
