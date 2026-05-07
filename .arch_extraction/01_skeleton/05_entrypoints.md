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
- **健康检查**：`GET /api/health`（由 `service-manager.ps1` 和 Docker deploy.sh 轮询）

### 2. Shell 核心调度器: `scripts/service-manager.ps1`

- **如何运行**：`powershell -File service-manager.ps1 <start|stop|restart|status|logs|kill>`
- **核心能力**：端口冲突检测、健康检查、同步启停、graceful shutdown
- **所有 .bat 的委托目标**：`start-all.bat` → `service-manager.ps1 start`，同理 stop/restart/check-status

### 3. CostView CLI: `CostView/src/__main__.py`

- **如何运行**：`python -m src [options]`
- **支持参数**：`--fetch-auto`, `--process`, `--aggregate`, `--pipeline`, `--query {fills|raw-fills|log|orders|tickers|summary}`, `--schedule`, `--schedule-once`, `--schedule-time`, `--rebuild-processed`, `--rebuild-aggregated`, `--status`, `--force`, `--bdib`, `--db-access`, `--process-date`, `--process-range`
- **核心调用**：`run_full_pipeline()` / `FillFetch.fetch_range_aggregated()` / `QueryEngine.query_*()` 等
- **分层调用**：
  ```
  __main__.py → pipeline.run_full_pipeline()
                           → run_process() → processed_fills_db
                           → run_aggregate() → bdib_daily_summary
                           → run_order_labels()
  ```

### 4. 定时调度: `CostView/scripts/daily_update.py`

- **如何运行**：
  - 交互式：`python daily_update.py`（进入 schedule 循环，默认 18:00）
  - 单次：`python daily_update.py --once`（Windows Task Scheduler 调用）
- **核心调用**：`run_daily_pipeline()` → fetch + process + BDIB + manifest
- **外部触发**：Windows Task Scheduler（通过 `install_scheduler.py` 注册）

### 5. Docker 部署: `scripts/deploy/deploy.sh`

- **如何运行**：`./deploy.sh start|stop|restart|status|logs|update|backup`
- **内部调用**：`docker compose up -d` → Nginx(80) 反代 Backend(3000)
- **健康检查**：`curl http://localhost:3000/api/health`

### 6. MCP 知识服务器: `scripts/mcp/knowledge-server.py`

- **如何运行**：由 AI 客户端通过 stdio 协议调用（非手动启动）
- **核心调用**：`mcp.run(transport="stdio")`

---

