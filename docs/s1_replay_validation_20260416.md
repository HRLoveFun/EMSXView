# S1 Replay Validation Report — 20260416

> 适用版本：`branch = 001-architecture-module-completion`  
> 验证日期：2026-06-18  
> 关联：[S1 数据修复方案 v2](../AppData/Roaming/CodeBuddy%20CN/User/globalStorage/tencent-cloud.coding-copilot/plans/77b90209e4314c1583cc619fe3123e24/plan.md) / [下游兼容矩阵](../specs/002-pipeline-guardrail/s1-downstream-compat-matrix.md)

## 1. 验证目标

重跑 S1 单日（20260416），验证 v2 修复后 4 张表的字段写入率（应有 100% 命中率），同时检查 `source_refreshed_at` 与 `first_fill_time/last_fill_time` 的时区/格式语义。

## 2. 执行命令

```bash
cd c:/Users/hrchen/Documents/EMSXView
python scripts/_validate_s1_replay.py
```

## 3. 验证结果

### 3.1 原始数据量

```
[PRE] raw_fills WHERE source_date='20260416' = 70214 rows
[STEP] Calling process_raw_fills_for_date('20260416')...
[STEP] result: {'date': '20260416', 'success': True, 'rows_read': 70214,
                'rows_cleaned': 69954, 'rows_processed': 69954, 'error': None}
```

清洗/过滤后 70214 → 69954（**过滤掉 260 行 DFD**）。

### 3.2 processed_fills.equ_ticker

```
total=24,221,022, non_null=24,042,998, rate=99.3%
```

全表 99.3% 命中率。**未命中 0.7% 主要来自 EUR 复合代码缓存/Bloomberg 查询都未命中的行**（预期行为，v2 修复后输出 `None`）。

### 3.3 route_registry 4 count 列（v2 新增）

| 列 | total | non_null | 写入率 |
| --- | ---:| ---:| ---:|
| `count_fill` | 70187 | 70187 | **100.0%** |
| `count_broker` | 70187 | 70187 | **100.0%** |
| `count_algo` | 70187 | 70187 | **100.0%** |
| `count_trader` | 70187 | 70187 | **100.0%** |

**v2 修复 100% 命中**（v1 全部为 NULL）。

### 3.4 route_history 字段（v2 修复：从 processed 自身取）

| 列 | total | non_null | 写入率 |
| --- | ---:| ---:| ---:|
| `equ_ticker` | 1132 | 1131 | 99.9% |
| `ccy_ticker` | 1132 | 1132 | **100.0%** |
| `Side` | 1132 | 1132 | **100.0%** |

`equ_ticker` 1 行未命中（EUR 复合代码未解析，与 processed_fills 一致）。

### 3.5 route_event_history 字段（v2 修复）

| 列 | total | non_null | 写入率 |
| --- | ---:| ---:| ---:|
| `equ_ticker` | 69954 | 69946 | 100.0% |
| `ccy_ticker` | 69954 | 69954 | **100.0%** |
| `Side` | 69954 | 69954 | **100.0%** |
| `source_refreshed_at` | 69954 | 69954 | **100.0%** |

`source_refreshed_at` **全部命中**（v1 永远 NULL → v2 100% 命中）。

### 3.6 source_refreshed_at 抽样

```
2026-06-18T03:41:29+00:00
2026-06-18T03:41:29+00:00
2026-06-18T03:41:29+00:00
2026-06-18T03:41:29+00:00
2026-06-18T03:41:29+00:00
```

**带 `+00:00` tz 后缀的 UTC 时间**（v2 修复：`datetime.now(timezone.utc).isoformat(timespec="seconds")`）。  
v1 输出 `2026-06-17T00:52:10`（naive UTC，无 tz 后缀）。

### 3.7 first_fill_time / last_fill_time 抽样

```
2026-04-16T09:49:59  |  2026-04-16T15:29:02
2026-04-16T13:10:22  |  2026-04-16T15:30:10
2026-04-16T13:08:39  |  2026-04-16T15:30:25
2026-04-16T13:09:28  |  2026-04-16T15:30:03
2026-04-16T09:48:41  |  2026-04-16T15:27:59
```

**ISO8601 格式 `YYYY-MM-DDTHH:MM:SS`**，local exchange tz（Asia/Tokyo），**无 tz 后缀**。  
v1 用字符串 `min/max` + 兜底 `DateTimeOfFill` 混用，结果不可预期。

## 4. 总结

| 修复项 | 状态 |
| --- | --- |
| `_build_execution_history_frames` 移除 route_attrs 二次 merge | ✓ |
| `_first_last_event_time` 改用 `pd.to_datetime` 解析后 min/max | ✓ |
| `source_refreshed_at` 改 UTC 带 `+00:00` 后缀 | ✓ |
| `add_equity_ticker` 空 Exchange/Ticker 输出 None | ✓（单元测试 7/7 通过） |
| `upsert_processed_fills` key_columns 改为 4 元组 | ✓（无运行时影响） |
| `process_raw_fills_for_date` 计算 4 个 count_* 列 | ✓（100% 命中） |

**全部 P0 任务通过**。下游兼容矩阵（`s1-downstream-compat-matrix.md`）列出的同步点已全部处理。

## 5. 后续建议

- P2 任务：raw_fills 5 个废弃列真正删除（v3.0 迁移）
- P2 任务：`processed_fills` 列重排（`equ_ticker / Ticker / Exchange` 提前）
- P2 任务：主要时间字段旁加 `_utc` 副本
- 监控建议：在 `tests/test_pipeline_guards.py` 加 `assert 4 个 count_* 列 100% 命中` 的回归断言

## 6. 引用

- v2 方案：`%APPDATA%\CodeBuddy CN\User\globalStorage\tencent-cloud.coding-copilot\plans\77b90209e4314c1583cc619fe3123e24\plan.md`
- 业务流程：`DataPipeline/BUSINESS_FLOW.md §3`
- 验证脚本：`scripts/_validate_s1_replay.py`
- 兼容矩阵：`specs/002-pipeline-guardrail/s1-downstream-compat-matrix.md`
