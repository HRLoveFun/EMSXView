# 入口点清单

> **数据来源**：05a (`__main__` 块) / 05b (CLI 框架) / 05c (package entry_points) / 05d (Web 入口) / 05e (README 命令) / 05f (Shell 脚本) / 05g (定时调度) / 05h (git 修改频率) / 05_real_entrypoints (分类结果) / 05_reverse_trace (外部触发)
>
> **总览**：EMSX 项目有 **4 类入口**：Web API（FastAPI 75+ 路由）、CLI（`python <script>`）、Shell 包装（`.bat`/`.ps1`）、后台调度（`schedule` 库 + Windows Task Scheduler）。无 `console_scripts` 或 `entry_points` 声明（05c 为空），所有入口通过 `python <script>` 或 Shell 脚本间接调用。

---

## 主入口（External — 用户/系统会调用）

### 1. Web 服务: `ExecutionView/backend/api/main.py`

- **如何运行**：`python start_server.py` 或 `start-services.bat`
- **FastAPI 实例**：`app = FastAPI(title="EMSX Trading API")` (L288)
- **核心调用**：`uvicorn.run("main:app", host, port)` → 注册 75+ 路由 → Bloomberg 实时订阅
- **启动生命周期**：
  1. `load_dotenv()` 加载 `.env`
  2. `Settings` 单例初始化
  3. `app.on_event("startup")` → `bloomberg_adapter.connect()` (async)
  4. 后台线程启动：emsx-subscription / mktdata-subscription
- **证据**：05a (L384 `__main__` 块 8 行), 05d (1 个正式 FastAPI 入口), 05e (QUICKSTART.md + docs/CLAUDE.md), 05f (所有 .bat/.ps1 最终指向此文件), 05h (git 修改 9 次，代码文件中最高频)
- **健康检查**：`GET /api/health`（由 `service-manager.ps1` 和 Docker deploy.sh 轮询）

### 2. Web 备用启动器: `ExecutionView/backend/api/start_server.py`

- **如何运行**：`python start_server.py`（固定 host=0.0.0.0:3000）
- **核心调用**：`uvicorn.run("main:app", ...)`
- **与 #1 的关系**：功能重叠；`start_server.py` 是 `.bat`/`.ps1` 的实际调用目标（见 `service-manager.ps1` L52 配置）
- **证据**：05a (L15 `__main__` 块 14 行), 05f (`service-manager.ps1` 配置 `Script = "ExecutionView\backend\api\start_server.py"`)

### 3. Shell 复合入口: `start-services.bat`

- **如何运行**：双击 / 命令行 `start-services.bat`
- **内部调用链**：
  1. 后端：`cd ExecutionView\backend\api && python start_server.py` (port 3000)
  2. 前端：`cd ExecutionView\frontend && npm run dev` (port 5173)
- **证据**：05f (L52/L69 显式命令), 05e (QUICKSTART.md 首推入口)

### 4. Shell 核心调度器: `scripts/service-manager.ps1`

- **如何运行**：`powershell -File service-manager.ps1 <start|stop|restart|status|logs|kill>`
- **核心能力**：端口冲突检测、健康检查、同步启停、graceful shutdown
- **所有 .bat 的委托目标**：`start-all.bat` → `service-manager.ps1 start`，同理 stop/restart/check-status
- **证据**：05f (6 个 .bat 全部委托此脚本), 05e (QUICKSTART.md 提及)

### 5. CLI: `CostView/src/__main__.py`

- **如何运行**：`python -m src [options]`
- **支持参数**：`--fetch-auto`, `--process`, `--aggregate`, `--pipeline`, `--query {fills|raw-fills|log|orders|tickers|summary}`, `--schedule`, `--schedule-once`, `--schedule-time`, `--rebuild-processed`, `--rebuild-aggregated`, `--status`, `--force`, `--bdib`, `--db-access`, `--process-date`, `--process-range`
- **核心调用**：`run_full_pipeline()` / `FillFetch.fetch_range_aggregated()` / `QueryEngine.query_*()` 等
- **证据**：05a (L327 `__main__`, main() 函数 250+ 行), 05b (argparse 30+ 参数), 05e (CostView/README.md 列举 `python -m src` 6 种用法)
- **分层调用**：
  ```
  __main__.py → pipeline.run_full_pipeline()
                           → run_process() → processed_fills_db
                           → run_aggregate() → bdib_daily_summary
                           → run_order_labels()
  ```

### 6. CLI: `CostView/src/fill_fetch.py`

- **如何运行**：`python -m src.fill_fetch` 或 `python -m src --fetch`
- **核心调用**：`FillFetch` 类 → Bloomberg EMSX API 抓取 fill 数据
- **证据**：05a (L1136 `__main__`), 05b (argparse), 被 `__main__.py` 通过 `--fetch` 调用

### 7. 定时调度: `CostView/scripts/daily_update.py`

- **如何运行**：
  - 交互式：`python daily_update.py`（进入 schedule 循环，默认 18:00）
  - 单次：`python daily_update.py --once`（Windows Task Scheduler 调用）
- **核心调用**：`run_daily_pipeline()` → fetch + process + BDIB + manifest
- **外部触发**：Windows Task Scheduler（通过 `install_scheduler.py` 注册）
- **证据**：05a (L186 `__main__`), 05b (argparse), 05g (schedule 库 + Windows Task Scheduler), 05e (CostView/README.md)

### 8. Windows 计划任务安装器: `CostView/scripts/install_scheduler.py`

- **如何运行**：`python install_scheduler.py [--time 08:30] [--uninstall] [--status]`
- **核心调用**：`schtasks.exe /Create /TN "CostView_DailyUpdate" /TR "python daily_update.py --once"`
- **证据**：05a (L130 `__main__`), 05g (cron/schedule 匹配), 05e (README 文档)

### 9. Docker 部署: `scripts/deploy/deploy.sh`

- **如何运行**：`./deploy.sh start|stop|restart|status|logs|update|backup`
- **内部调用**：`docker compose up -d` → Nginx(80) 反代 Backend(3000)
- **健康检查**：`curl http://localhost:3000/api/health`
- **证据**：05f (唯一 .sh 文件)

### 10. MCP 知识服务器: `scripts/mcp/knowledge-server.py`

- **如何运行**：由 AI 客户端通过 stdio 协议调用（非手动启动）
- **核心调用**：`mcp.run(transport="stdio")`
- **证据**：05a (L317 `__main__`)

---

## 次要入口（日常运维，按需调用）

### CostView 数据工具

| # | 脚本 | 如何运行 | 核心调用 | 证据 |
|---|---|---|---|---|
| 11 | `CostView/src/daily_metrics_calculator.py` | `python daily_metrics_calculator.py --date 20260115` 或 `--all` | `CalculateDailyMetrics.run_for_date()` | 05a, 05b |
| 12 | `CostView/src/validate_raw_fills.py` | `python validate_raw_fills.py [options]` | `main()` 完整 CLI 逻辑 | 05a |
| 13 | `CostView/src/secure_config.py` | `python secure_config.py --validate` 或 `--setup` | `SecureConfigManager` 交互式配置 | 05a, 05b |
| 14 | `CostView/scripts/backfill_raw_bdib.py` | `python backfill_raw_bdib.py [options]` | `main()` — 698 行大脚本 | 05a, 05b |
| 15 | `CostView/scripts/backfill_bdib_history.py` | `python backfill_bdib_history.py --lookback 25 [--dry-run]` | `run_backfill()` | 05a, 05b |
| 16 | `CostView/scripts/backfill_regime.py` | `python backfill_regime.py` | `main()` | 05a |
| 17 | `CostView/scripts/fetch_macro_calendar.py` | `python fetch_macro_calendar.py --start --end` | `main()` | 05a, 05b |
| 18 | `CostView/scripts/run_attribution.py` | `python run_attribution.py --inspect --by broker algo` | `main()` | 05a, 05b, 05e (docs/RESEARCH_NOTES 提及) |
| 19 | `CostView/scripts/seed_macro_events.py` | `python seed_macro_events.py` | `main()` | 05a |

### CostView Regime 维护

| # | 脚本 | 核心调用 | 证据 |
|---|---|---|---|
| 20 | `CostView/src/regime/migrations/apply.py` | `main()` — regime.db 迁移 | 05a, 05b |
| 21 | `CostView/src/regime/sync_macro_calendar.py` | CSV → ref_macro_event_calendar | 05a, 05b |
| 22 | `CostView/src/regime/sync_macro_event_dict.py` | JSON → ref_macro_event_dict | 05a, 05b |
| 23 | `CostView/src/regime/sync_market_mapping.py` | JSON → ref_market_mapping | 05a, 05b |
| 24 | `CostView/src/regime/validate_macro_calendar.py` | 校验 macro_calendar.csv | 05a, 05b |

### 项目级运维脚本

| # | 脚本 | 如何运行 | 核心调用 | 证据 |
|---|---|---|---|---|
| 25 | `scripts/workflow/auto_runner.py` | `python auto_runner.py run-step/check-step/run-all` | `main()` 757 行 | 05a, 05b |
| 26 | `scripts/workflow/validate_phase_gate.py` | `python validate_phase_gate.py --mode` | `main()` | 05a, 05b |
| 27 | `scripts/workflow/sync_execution_status.py` | `python sync_execution_status.py` | `main()` | 05a, 05b |
| 28 | `scripts/workflow/generate_handoff_snapshot.py` | `python generate_handoff_snapshot.py` | `main()` | 05a, 05b |
| 29 | `scripts/workflow/collect_ci_status.py` | `python collect_ci_status.py` | `main()` | 05a, 05b |
| 30 | `scripts/import_excel_fills.py` | `python import_excel_fills.py --dry-run/--execute` | `main()` 951 行 | 05a, 05b |
| 31 | `scripts/fetch_and_inspect.py` | `python fetch_and_inspect.py --team` | `run_full_inspection()` | 05a, 05b |
| 32 | `scripts/sync-metrics.py` | `python sync-metrics.py` | `main()` | 05a |
| 33 | `scripts/run_attribution_notebook.py` | `python run_attribution_notebook.py` | papermill 执行 | 05a |

### Git Hooks（IDE Agent 调用）

| # | 脚本 | 触发时机 | 行为 | 证据 |
|---|---|---|---|---|
| 34 | `scripts/hooks/session-context.py` | SessionStart | 注入知识库摘要到上下文 | 05a |
| 35 | `scripts/hooks/session-summary.py` | SessionEnd | 记录会话摘要 | 05a |
| 36 | `scripts/hooks/log-change.py` | 文件变更 | 记录变更事件 | 05a |

---

## 调试入口（开发者临时使用，不算正式入口）

| 脚本 | 原因 | 证据 |
|---|---|---|
| `CostView/examples/secure_uuid_example.py` | 示例代码 | 05_real_entrypoints: ❌ |
| `scripts/diagnose/diagnose_exchange_ticker_issue.py` | 一次性诊断 | 05_real_entrypoints: ❌ |
| `scripts/diagnose/diagnose_odd_lot.py` | 调试入口，调用 `test_api()` | 05_real_entrypoints: ❌ |
| `scripts/diagnose/diagnose_orders_display.py` | 一次性诊断 | 05_real_entrypoints: ❌ |
| `CostView/tests/test_*.py` (5 个) | 测试文件 | 05_real_entrypoints: ❌ |
| `CostView/_archive/` (4 个) | 归档脚本 | 05_real_entrypoints: ❌ |
| `scripts/_archive/` (4 个) | 归档脚本 | 05_real_entrypoints: ❌ |
| `CostView/test_comprehensive.py` | 测试文件 | 05_real_entrypoints: ❌ |
| `CostView/test_pipeline_guards.py` | 测试文件 | 05_real_entrypoints: ❌ |

---

## API 路由清单（FastAPI, 75+ 端点）

后端入口：`ExecutionView/backend/api/main.py`（L288: `app = FastAPI(title="EMSX Trading API")`）

### 连接与健康（`routers/connection.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 根路径 |
| GET | `/api/health` | 健康检查（service-manager + Docker 轮询） |
| GET | `/api/connection` | 连接状态 |
| GET | `/api/startup-status` | 启动阶段诊断 |
| POST | `/api/connection/reconnect` | Bloomberg 重连 |

### 认证（`routers/auth.py`）

| 方法 | 路径 |
|---|---|
| POST | `/api/auth/login` |

### 订单与执行（`routers/orders.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/orders/status` | 订单状态摘要 |
| GET | `/api/orders` | 订单列表 |
| POST | `/api/orders/modify` | 修改订单 |
| POST | `/api/orders/route` | 路由订单 |
| POST | `/api/orders/batch-update` | 批量更新 |
| POST | `/api/orders/batch-route` | 批量路由 |
| GET | `/api/orders/refresh` | 刷新缓存 |
| POST | `/api/orders/{order_id}/cancel` | 取消订单 |
| POST | `/api/executions` | 执行详情 |
| POST | `/api/executions/{parent_id}/command` | 执行指令 |
| GET | `/api/executions/{parent_id}` | 单个执行 |
| GET | `/api/executions` | 执行列表 |
| GET | `/api/executions/handoff/candidates` | 手递交接候选 |
| POST | `/api/executions/handoff/post-trade` | 盘后交接 |

### 路由（`routers/routes.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/routes` |
| POST | `/api/routes/cancel` |
| POST | `/api/routes/modify` |
| POST | `/api/routes/batch-modify` |
| GET | `/api/routes/diagnose-strategy-rate` |
| GET | `/api/routes/reference-enums` |

### 经纪商（`routers/broker.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/trader-info` |
| GET | `/api/asset-class` |
| GET | `/api/broker-strategies` |
| GET | `/api/broker-strategy-info` |
| GET | `/api/brokers` |
| GET | `/api/broker-algorithms` |
| POST | `/api/broker-algorithms/refresh` |
| GET | `/api/broker-algorithms/status` |
| GET | `/api/broker-recommendations` |

### 市场视图（`routers/marketview.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/marketview/snapshot` |
| GET | `/api/marketview/intraday-features` |
| POST | `/api/marketview/handoff/execution` |

### 经纪商-市场映射（`routers/market_broker_mapping.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/market-broker-mapping` |
| PUT | `/api/market-broker-mapping/selection` |
| POST | `/api/market-broker-mapping/unlock` |
| PUT | `/api/market-broker-mapping/roster` |

### 路由计划（`routers/route_plans.py`）

| 方法 | 路径 |
|---|---|
| GET/POST | `/api/route-plans` |
| GET/PUT/DELETE | `/api/route-plans/{plan_id}` |
| POST | `/api/route-plans/{plan_id}/test-match` |
| POST | `/api/route-engine/apply/{order_id}` |
| GET | `/api/sub-order-proposals` |
| POST | `/api/sub-order-proposals/{id}/confirm` |
| POST | `/api/sub-order-proposals/batch-confirm` |
| POST | `/api/sub-order-proposals/{id}/reject` |

### TCA / CostView（`routers/costview.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/tca/analyze` | TCA 分析 |
| POST | `/api/tca/scorecard` | TCA 记分卡 |
| POST | `/api/tca/trigger-update` | **触发 CostView 管道更新**（子进程） |
| GET | `/api/tca/update-status/{job_id}` | 管道进度查询 |
| POST | `/api/tca/recommendations/pin` | 固定 TCA 建议 |
| GET | `/api/tca/handoff/post-trade/{order_id}` | 盘后 TCA 交接 |
| GET | `/api/costview/regime-distribution` | 市场状态分布 |

### 数据库管理（`routers/database.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/db/overview` |
| GET | `/api/db/{key}/summary` |
| GET | `/api/db/{key}/integrity` |
| GET | `/api/db/{key}/tables/{table}/schema` |
| GET | `/api/db/{key}/tables/{table}/sample` |
| POST | `/api/db/update` |
| GET | `/api/db/update-status/{job_id}` |

### 执行历史（`routers/execution_history.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/execution-history/fills` |
| GET | `/api/execution-history/orders` |
| GET | `/api/execution-history/routes` |

### 调试（`routers/debug.py`）

| 方法 | 路径 |
|---|---|
| GET | `/api/debug/round-lot-sizes` |
| POST | `/api/debug/query-round-lot` |

### WebSocket

| 类型 | 路径 | 说明 |
|---|---|---|
| WebSocket | `/ws/orders` | 实时订单推送 |

---

## 定时任务

### 进程内调度

| 触发方式 | 所在文件 | 说明 |
|---|---|---|
| `schedule` 库 | `CostView/scripts/daily_update.py` (L174) | 每天 `--time`（默认 18:00）执行 `run_daily_pipeline()` |
| `asyncio.create_task` | `ExecutionView/backend/api/main.py` (L277) | app 启动时异步连接 Bloomberg |
| `threading.Thread` | `bloomberg_adapter.py` (L447) | Bloomberg 订单订阅后台线程 |
| `threading.Thread` | `bloomberg_adapter.py` (L455) | Bloomberg 行情订阅后台线程 |
| `threading.Thread` | `_pipeline_jobs.py` (L212) | CostView 管道子进程，由 `/api/tca/trigger-update` 触发 |
| `ThreadPoolExecutor` | `CostView/src/pipeline.py` (L20) | 增量处理并行任务池 |

### 外部调度

| 触发方式 | 文件 | 说明 |
|---|---|---|
| Windows Task Scheduler | `CostView/scripts/install_scheduler.py` | `schtasks.exe` 注册 `python daily_update.py --once` |
| Docker Compose | `scripts/deploy/deploy.sh` | `docker compose up -d`，Nginx:80 → Backend:3000 |
| Windows Task Scheduler | `scripts/cleanup-logs.ps1` | 日志清理，建议每日 3am（需手动注册） |

---

## 配置入口

### 核心配置

| 文件 | 技术 | 说明 | 证据 |
|---|---|---|---|
| `ExecutionView/backend/api/config.py` | `os.getenv` + 校验 | 后端全局配置单例 | 05e (CLAUDE.md) |
| `.env` | `load_dotenv()` | 活跃环境变量 (main.py:29-30) | 05e |
| `ExecutionView/backend/.env.example` | — | 后端配置模板 | 05e |
| `ExecutionView/frontend/.env` | Vite env | 前端 API 地址等 | — |
| `CostView/.env.example` | — | CostView 配置模板 | — |

### CostView 管道配置

| 文件 | 技术 | 说明 | 证据 |
|---|---|---|---|
| `CostView/src/processing_config.py` | `ProcessingConfig` 类 | 中心化配置：目录/DB/日志/BDIB 参数 | 05e (README) |
| `CostView/src/secure_config.py` | UUID + 环境变量/JSON | Bloomberg EMSX 凭据管理 | 05a (argparse --setup/--validate) |
| `CostView/src/attribution/config.py` | SQLite | 归因分析配置 | — |
| `CostView/src/regime/config.py` | SQLite | 市场状态阈值配置 | — |

### 数据入口

| 入口 | 配置方式 | 说明 |
|---|---|---|
| Excel 文件目录 | `Config.EXCEL_DIR` | fill 数据源（`import_excel_fills.py`） |
| `raw_fills.db` | `Config.RAW_FILLS_DB` | 原始 fill 数据库 |
| `processed_fills.db` | `Config.PROCESSED_FILLS_DB` | 处理后 fill 数据库 |
| `regime.db` | `Config.REGIME_DB` | 市场状态数据库 |
| Bloomberg API | `Config.BLOOMBERG_HOST/PORT` | 实时数据+交易网关 |

---

## 调用链总图

```
用户 ──双击──▶ start-services.bat
                │
                ├─▶ python ExecutionView/backend/api/start_server.py
                │       └─▶ uvicorn main:app (FastAPI, :3000)
                │            ├─▶ startup: bloomberg_adapter.connect()
                │            ├─▶ threads: emsx-subscription, mktdata-subscription
                │            └─▶ 75+ API routes + /ws/orders

                └─▶ npm run dev (ExecutionView/frontend/, :5173)
                        └─▶ App.tsx → services/api.ts → :3000

用户 ──双击──▶ 重启服务.bat
                └─▶ scripts/service-manager.ps1 restart
                        ├─▶ stop (kill :3000, :5173)
                        └─▶ start (同上)

定时 ──Windows Task Scheduler──▶ python daily_update.py --once
                                        └─▶ run_daily_pipeline()
                                              ├─▶ FillFetch → raw_fills.db
                                              ├─▶ pipeline.run_process() → processed_fills.db
                                              ├─▶ daily_metrics_calculator → bdib_daily_summary
                                              └─▶ manifest 写入

开发 ──CLI──▶ python -m src [options]
                ├─▶ --fetch-auto → FillFetch.fetch_range_aggregated()
                ├─▶ --pipeline → run_full_pipeline()
                ├─▶ --query → QueryEngine.query_*()
                └─▶ --schedule → schedule.every().day().do()

AI ──stdio──▶ scripts/mcp/knowledge-server.py
                └─▶ mcp.run(transport="stdio")

运维 ──bash──▶ scripts/deploy/deploy.sh start
                └─▶ docker compose up (Nginx:80 → Backend:3000)
```

---

## 修改频率排名（05h，近 3 个月）

| 排名 | 文件 | 次数 | 角色 |
|---|---|---|---|
| 1 | `.github/knowledge/iteration-log.md` | 20 | 知识库（自动更新） |
| 7 | **`ExecutionView/backend/api/main.py`** | 9 | **后端装配入口** |
| 11 | **`ExecutionView/backend/api/services/bloomberg_adapter.py`** | 7 | Bloomberg 适配器枢纽 |
| 15 | **`ExecutionView/frontend/src/App.tsx`** | 6 | **前端壳入口** |
| 14 | `ExecutionView/frontend/src/services/api.ts` | 6 | 前端 API 层 |
| 19 | `CostView/src/pipeline.py` | 5 | CostView 管线核心 |

> `main.py`(9次) 确认最核心后端入口；`App.tsx`(6次) 确认唯一前端壳入口；`bloomberg_adapter.py`(7次) 非入口但是被调用最多的服务层枢纽。
