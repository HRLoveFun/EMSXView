# DatabaseView API Contract (/api/db/*)

> 从 `docs/spec/memory.md` 分离出的独立 API 文档
> Last updated: 2026-05-07

DatabaseView 是 frontend/ 的第 4 个顶层模块，负责可视化 CostView
SQLite 数据库族的交易日期覆盖、行数与健康状态，并承载唯一的"触发增量更新"入口。

## 路由注册

- Router：`backend/api/routers/database.py`
- Pipeline job 注册表：`backend/api/routers/_pipeline_jobs.py`
  （由 database 和 costview 两个 router 共享，保证"一个活动作业"语义跨端点一致）
- 只读统计查询：`platform_data/repositories.py`

## 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET  | `/api/db/overview` | 所有注册数据库的概览（size、date range、health）|
| GET  | `/api/db/{key}/summary` | 指定库的表级日期覆盖 + 每日行数序列 |
| GET  | `/api/db/{key}/integrity` | 有界完整性检查（仅扫描最近窗口）|
| GET  | `/api/db/{key}/tables/{table}/schema` | 列与索引元数据（PRAGMA table_info / index_list）|
| GET  | `/api/db/{key}/tables/{table}/sample?limit=N` | 最近 N 行样本（N≤200）+ 字段级 NULL/同值异常 |
| POST | `/api/db/update` | 触发 daily 增量 pipeline（仅 localhost）|
| GET  | `/api/db/update-status/{job_id}` | 轮询作业状态 |

## 注册的数据库 key（稳定标识）

- `raw_fills`、`processed_fills`、`raw_bdib`、`fill_bdib`、`fill_fetch_history`

## 性能契约

- overview 使用 MAX(\_rowid\_) 近似 + 分离的 MIN / MAX 查询，在 70 GB 级 raw_bdib.db 上仍在 100 ms 内返回。
- summary 的 per-date 计数通过日期索引 GROUP BY 执行。
- integrity 检查一律限制在最近窗口（rowid 最近 200k，或日期 ≥ latest−45 天）。

## 兼容性 Alias

- `/api/tca/trigger-update` 与 `/api/tca/update-status/{job_id}` 保留为已弃用别名，内部转发到 `_pipeline_jobs.trigger_pipeline()` / `get_job()`。
- 回填（backfill）脚本保持 CLI-only，UI **不**暴露回填入口。
