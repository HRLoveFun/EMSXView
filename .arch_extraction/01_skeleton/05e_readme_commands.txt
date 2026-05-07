C:\Users\hrchen\Documents\EMSX\.arch_extraction\01_skeleton\05_entrypoints.md:3:> **总览**：EMSX 项目有 **3 类入口**：CLI（`python <script>`）、API（FastAPI 75+ 路由）、后台调度（`schedule` 库 + Windows Task Scheduler）。无 `console_scripts` 或 `entry_points` 包装，所有入口通过 `python <script>` 或 `.bat`/`.ps1` 间接调用。
C:\Users\hrchen\Documents\EMSX\.arch_extraction\01_skeleton\05_entrypoints.md:13:| `ExecutionView/backend/api/main.py` `__main__` (L384) | FastAPI 主服务入口，`uvicorn.run("main:app", ...)` | `python main.py` |
C:\Users\hrchen\Documents\EMSX\.arch_extraction\01_skeleton\05_entrypoints.md:14:| `ExecutionView/backend/api/start_server.py` `__main__` (L15) | 备用启动器，固定 host=0.0.0.0:3000，由 `.bat`/`.ps1` 实际调用 | `python start_server.py` |
C:\Users\hrchen\Documents\EMSX\.arch_extraction\01_skeleton\05_entrypoints.md:92:| `scripts/deploy/start-frontend.ps1` | 清理旧进程后运行 `npm run dev` |
C:\Users\hrchen\Documents\EMSX\.arch_extraction\01_skeleton\05_entrypoints.md:132:| **Windows Task Scheduler** | `CostView/scripts/install_scheduler.py` | 通过 `schtasks.exe` 安装/卸载每日更新定时任务，调用 `python daily_update.py --once` |
C:\Users\hrchen\Documents\EMSX\.github\agents\error-resolver.agent.md:27:- Backend requires RESTART after Python code changes
C:\Users\hrchen\Documents\EMSX\.github\agents\error-resolver.agent.md:33:- CostView: `CostView/src/` — Python pipeline with SQLite
C:\Users\hrchen\Documents\EMSX\.github\agents\task-planner.agent.md:25:- For EMSX tasks: include "restart backend" after Python edits
C:\Users\hrchen\Documents\EMSX\.github\instructions\task-planning.instructions.md:57:- Backend changes require restart — include "restart backend" as a sub-task after Python edits
C:\Users\hrchen\Documents\EMSX\.github\knowledge\error-patterns.md:132:5. Validate with `python -m unittest CostView.test_pipeline_guards`.
C:\Users\hrchen\Documents\EMSX\.github\knowledge\error-patterns.md:144:- **Root Cause**: The order-level summary builder averaged route metrics with raw `sum(...) / len(...)` logic. Some route metric dictionaries can contain `None` for one or more summary fields, so Python attempts `0 + None` and raises a TypeError instead of skipping missing metrics.
C:\Users\hrchen\Documents\EMSX\.github\knowledge\error-patterns.md:149:4. Validate by running `python -m unittest CostView.test_pipeline_guards` and calling `POST /api/tca/analyze`.
C:\Users\hrchen\Documents\EMSX\.github\knowledge\error-patterns.md:163:1. Change `CostView/src/exchange_tz.py` `batch_convert_ny_to_local()` to return tz-naive local wall-clock datetimes so mixed exchanges preserve their local time values. 2. In `CostView/src/tca_query_service.py`, derive route `start_time`/`end_time` from `DateTimeOfFill + Exchange` instead of trusting stored `exchange_exec_time` only. 3. Compare `raw_bdib.mkt_timestamp` via `substr(mkt_timestamp, -8)` so both time-only and datetime-formatted rows work. 4. Compute `volume_pct_adv5/20` from order filled volume, not from market `total_volume`. 5. Add `daily_volatility` to the order summary and bind the Analysis order-table `Volatility` column to it while keeping `intraday_volatility` for detailed intraday views. 6. Add a raw_bdib-based fallback in `tca_query_service.py` for missing route benchmark / tracking / volume metrics when bar data exists but legacy fill_bdib rows were built with bad local-time alignment. 7. Validate with `pytest CostView/tests/test_tca_query_service.py CostView/test_pipeline_guards.py` and `npm run build` in `ExecutionView/frontend`.
C:\Users\hrchen\Documents\EMSX\.github\knowledge\error-patterns.md:286:- **Resolution**: Use `python -m unittest CostView.tests.<module> -v` for CostView tests instead of pytest. All CostView tests inherit from `unittest.TestCase` so this works directly.
C:\Users\hrchen\Documents\EMSX\.github\knowledge\iteration-log.md:30:| 2026-04-21 | feat | TCA implementation | Phase 0-6 TCA module: enabled BDIB pipeline stages (daily_update.py), added bdib_daily_summary schema (raw_bdib_db.py), created daily_metrics_calculator.py (Stage 7), backfill_bdib_history.py, tca_query_service.py (parameterized multi-DB queries, OWASP-compliant), test_tca_query_service.py, routers/costview.py (3 FastAPI endpoints), registered in main.py, updated scheduler to 09:00, frontend: tca-api.ts + TcaFilterPanel + TcaOrderTable + TcaRouteTable + PriceDynamicChart + VolumeDynamicChart + TCAPage + App.tsx TCA tab | All TypeScript 0 errors, all Python files compile, 16/16 todos completed |
C:\Users\hrchen\Documents\EMSX\.github\knowledge\iteration-log.md:47:| 2026-04-21 17:12 | task | User requested CostView frontend implementation with shared shell, exports, and configurable threshold alerts | Implemented a lazy-loaded CostView module in ExecutionView/frontend with Overview/Analysis/Configure views, local threshold/config persistence, export flows, and threshold unit tests; validated with frontend build and tests | CostView is now integrated into the main frontend shell and verified by successful npm run build and npm test | manual |
C:\Users\hrchen\Documents\EMSX\.github\knowledge\iteration-log.md:53:| 2026-04-22 09:45 | error | User requested one-pass fix for pipeline `database is locked` failures and BDIB near-real-time warnings | Added SQLite busy-timeout configuration, serialized Stage 3 aggregate writes into guarded transactions, introduced a safe BDIB cutoff window in both the pipeline and fetch layer, and added targeted regression tests | Focused Python tests passed; Stage 3 now avoids concurrent write races on `processed_fills.db`, and morning pipeline runs will skip unsafe latest BDIB dates instead of flooding logs with near-real-time warnings | manual |
C:\Users\hrchen\Documents\EMSX\.github\knowledge\iteration-log.md:122:| 2026-04-23 17:06 | error | Acceptance suite failed because async realtime tests were collected without pytest-asyncio support | Verified ExecutionView/backend/api/requirements.txt already declares pytest-asyncio, installed pytest-asyncio==0.23.3 into the configured Python environment, and reran the same acceptance command | The requested acceptance suite switched from plugin-collection failures to a clean pass (20 tests) without any code rollback | manual |
C:\Users\hrchen\Documents\EMSX\.github\knowledge\iteration-log.md:289:- 前端: SettingsBoard 添加"路由方案管理"入口 | 所有后端 Python 文件编译通过，前端 tsc --noEmit 无类型错误。功能覆盖: RoutePlan CRUD, 多维匹配 (symbol/side/portfolio/trader/exchange), BROKER_SPLIT/TIME_SCHEDULE/HYBRID 三种拆分策略, AUTO/MANUAL 激活模式, MANUAL_CONFIRM 提交模式, 批量确认调用现有 batch_route_service。 | manual |
C:\Users\hrchen\Documents\EMSX\.github\knowledge\user-needs.md:37:- **Proposed Automation**: A hook or instruction that reminds to restart backend after Python file edits in `ExecutionView/backend/`
C:\Users\hrchen\Documents\EMSX\.github\copilot-instructions.md:54:- **CostView**: Python pipeline with SQLite databases (`CostView/src/`)
C:\Users\hrchen\Documents\EMSX\.github\copilot-instructions.md:58:- Backend requires **restart** after Python code changes to take effect
C:\Users\hrchen\Documents\EMSX\.workbuddy\memory\2026-04-15.md:4:- 对 `CostView/src/` 全部 28 个 Python 模块执行了深度架构审查（~460KB / ~13000 行）
C:\Users\hrchen\Documents\EMSX\.workbuddy\memory\2026-04-15.md:18:- 遇到中文文件名编码问题，用 Python 原始字节模式解决
C:\Users\hrchen\Documents\EMSX\CostView\README.md:68:python -m src --setup-config
C:\Users\hrchen\Documents\EMSX\CostView\README.md:71:python -m src --validate-config
C:\Users\hrchen\Documents\EMSX\CostView\README.md:97:python -m src --setup-config
C:\Users\hrchen\Documents\EMSX\CostView\README.md:100:python -m src --validate-config
C:\Users\hrchen\Documents\EMSX\CostView\README.md:103:python -m src --date 2024-01-15
C:\Users\hrchen\Documents\EMSX\CostView\README.md:106:python -m src --date 2024-01-15 --uuid 1234
C:\Users\hrchen\Documents\EMSX\CostView\README.md:109:python -m src --start-date 2024-01-01 --end-date 2024-01-31
C:\Users\hrchen\Documents\EMSX\CostView\README.md:112:python -m src --date 2024-01-15 --no-prompt
C:\Users\hrchen\Documents\EMSX\CostView\README.md:115:python -m src --history
C:\Users\hrchen\Documents\EMSX\CostView\README.md:118:python -m src --stats
C:\Users\hrchen\Documents\EMSX\CostView\README.md:121:#### Python API
C:\Users\hrchen\Documents\EMSX\CostView\README.md:182:├── requirements.txt       # Python dependencies
C:\Users\hrchen\Documents\EMSX\CostView\README.md:204:python -m pytest tests/
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:28:cd ExecutionView/backend/api && python -m uvicorn main:app --port 3000
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:31:cd ExecutionView/frontend && npm run dev
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:38:| `npm run build` | 前端构建 |
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:39:| `npm run lint` | 前端代码检查 |
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:40:| `python -m py_compile ExecutionView/backend/api/main.py` | Python 语法检查 |
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:48:| 后端 | Python (FastAPI) + blpapi |
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:64:- [ ] 前端变更: `npm run lint` 通过
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:65:- [ ] 后端变更: `python -m py_compile` 通过
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:86:2. 运行 `npm run lint` 检查类型错误
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\CLAUDE.pre-2026-04-22.md:101:python -c "import socket; s=socket.socket(); s.connect(('localhost', 8194)); print('Connected')"
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\MEMORY.pre-2026-04-22.md:97:### Python Backend
C:\Users\hrchen\Documents\EMSX\docs\archive\2026-04-22\ORDERS_DISPLAY_DIAGNOSIS.md:111:python scripts/test_orders_display_fix.py
C:\Users\hrchen\Documents\EMSX\docs\RESEARCH_NOTES\2026-04-M2-broker-algo-v0.md:13:| Reproduction | `python -m CostView.scripts.run_attribution --inspect --start 2025-09-25 --end 2026-04-22 --by broker algo` |
C:\Users\hrchen\Documents\EMSX\docs\RESEARCH_NOTES\2026-04-M2-broker-algo-v0.md:146:_Reproducible via_ `python -m CostView.scripts.run_attribution --start 2025-09-25 --end 2026-04-22`
C:\Users\hrchen\Documents\EMSX\docs\CLAUDE.md:17:python start_server.py
C:\Users\hrchen\Documents\EMSX\docs\CLAUDE.md:21:npm run dev
C:\Users\hrchen\Documents\EMSX\docs\CLAUDE.md:47:- Python 后端改动后必须重启后端。
C:\Users\hrchen\Documents\EMSX\docs\CLAUDE.md:56:- 在 Execution/frontend 运行 npm run build
C:\Users\hrchen\Documents\EMSX\docs\DATA_DOMAIN.md:151:- No immediate rewrite into a single monorepo Python package layout.
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:25:- Python 后端改动后需要重启 backend
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:118:python -m pytest tests/test_platform_data_access.py tests/test_service_provider.py tests/test_db_bootstrap.py tests/test_projection_repositories.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:197:python -m pytest tests/test_bloomberg_adapter_refdata.py tests/test_connection_router.py tests/test_realtime_gateway.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:276:python -m pytest tests/test_bloomberg_adapter_routing.py tests/test_parent_child_execution.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:280:npm run build
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:355:python -m pytest tests/test_platform_data_access.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:359:npm run build
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:438:python -m pytest tests/test_tca_query_service.py test_pipeline_guards.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:442:npm run build
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:521:python -m pytest tests/test_fill_fetch.py tests/test_tca_query_service.py test_pipeline_guards.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:525:python -m pytest tests/test_service_provider.py tests/test_db_bootstrap.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:604:python -m pytest tests/test_tca_query_service.py test_pipeline_guards.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:608:npm run build
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:689:python -m pytest tests/test_platform_data_access.py tests/test_connection_router.py -q
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_TASK_TEMPLATES.md:693:npm run build
C:\Users\hrchen\Documents\EMSX\docs\EXECUTION_PLATFORM_WBS.md:189:| `c:/Users/hrchen/Documents/EMSX/.github/workflows/execution-platform-ci.yml` | create | CI entrypoint for backend/frontend/test gates | Matrix jobs for Python and Node; branch protections consume this workflow | P0-S0-03 |
C:\Users\hrchen\Documents\EMSX\docs\MEMORY.md:37:- Python 后端代码修改后需要重启后端才能生效。
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:57:- **Process**: Python (uvicorn)
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:65:- **Entry Point**: `Execution/frontend/` (npm run dev)
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:80:├── Launch Python process
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:107:├── Send SIGTERM to Python processes
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:149:# Kill all Python and Node processes
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:238:3. Check Python dependencies:
C:\Users\hrchen\Documents\EMSX\docs\SERVICE_MANAGEMENT.md:295:python start_server.py
C:\Users\hrchen\Documents\EMSX\ExecutionView\backend\README.md:94:│   ├── requirements.txt     # Python 依赖
C:\Users\hrchen\Documents\EMSX\ExecutionView\README.md:27:└── backend/               # Python FastAPI backend
C:\Users\hrchen\Documents\EMSX\ExecutionView\README.md:58:npm run dev        # Development server
C:\Users\hrchen\Documents\EMSX\ExecutionView\README.md:59:npm run build      # Production build
C:\Users\hrchen\Documents\EMSX\ExecutionView\README.md:62:## Backend (Python + FastAPI)
C:\Users\hrchen\Documents\EMSX\ExecutionView\README.md:82:- Python 3.11
C:\Users\hrchen\Documents\EMSX\AGENTS.md:34:- 前端代码修改后必须 `npm run build` 通过
C:\Users\hrchen\Documents\EMSX\AGENTS.md:136:| **QA** | Diff 提交 | 自动运行：lint → 后端 pytest → 前端 `npm run build` → 接口 smoke test；Bloomberg 字段变更额外校验订阅/模型/解析器一致性 | 查看质检报告 |
C:\Users\hrchen\Documents\EMSX\AGENTS.md:138:| **APPLY** | 获得批准 | 将变更合并到目标分支，验证合并结果；重启后端（如涉及 Python 变更） | 无 |
C:\Users\hrchen\Documents\EMSX\AGENTS.md:224:### 后端 (Python / FastAPI)
C:\Users\hrchen\Documents\EMSX\QUICKSTART.md:61:│   ├── backend/api/        # Python backend
C:\Users\hrchen\Documents\EMSX\README.md:71:**Backend:** Python 3.11 + FastAPI + Pydantic v2 + blpapi
C:\Users\hrchen\Documents\EMSX\README.md:127:│   ├── requirements.txt           # Python dependencies
C:\Users\hrchen\Documents\EMSX\README.md:166:- Python 3.11+ (for backend development)
C:\Users\hrchen\Documents\EMSX\README.md:191:npm run dev    # http://localhost:5173
C:\Users\hrchen\Documents\EMSX\README.md:214:| Backend | Python 3.11, FastAPI, Pydantic v2 |
C:\Users\hrchen\Documents\EMSX\README.md:222:| Scripts | PowerShell, Batch, Python |
C:\Users\hrchen\Documents\EMSX\项目功能构建规划.md:344:> - Tech stack: Python (FastAPI, pandas/polars, scipy), React/TypeScript, Bloomberg API.
