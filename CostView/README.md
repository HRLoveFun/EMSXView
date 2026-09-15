# CostView Module

> **Post-Trade TCA Analytics** · 🟡 **Beta** · Independent Microservice (port 8002)

---

## Overview

The **CostView** module provides post-trade TCA (Transaction Cost Analysis)
and broker recommendation services. It runs as an independent FastAPI service,
is a **read-only consumer** of the analytical SQLite stores (via `data_access/`,
all connections `mode=ro`), and never writes to any database.

> 成熟度分级定义见主 [README.md §0](../README.md#0-模块成熟度分级契约定义)。定级 **Beta** 的证据：213 个测试函数（`CostView/tests/`，7 个测试文件，pytest 实际收集 219 个用例，含 CLI 入口与黄金样本回归）；已知限制清单公开发布；13 个 API 端点全部可追溯到代码。欠缺（诚实列出）：测试覆盖率未量化（`pyproject.toml` 已配 pytest + coverage 但未设 `--cov-fail-under` 门槛）、无 CostView 专项运维手册（`docs/ops/service-management.md` 未覆盖本模块，故不进 GA）、黄金样本回归依赖冻结快照与 golden 基线（缺失时自动 skip）。

## Architecture

```
CostView/                          # CostView domain
├── pyproject.toml                 # Pip package (emsxview-costview)
├── api/                           # Independent microservice
│   ├── main.py                    # FastAPI app entry (<COSTVIEW_PORT>, default 8002)
│   ├── config.py                  # Service configuration
│   ├── requirements.txt           # Python dependencies
│   └── routers/
│       ├── costview.py            # TCA analysis endpoints (/api/tca/*)
│       └── monitoring.py          # Monitoring endpoints (/api/tca/monitoring/*)
├── src/
│   ├── tca_query_service.py       # TCA query orchestrator (reads tca_route_summary precomputed table)
│   ├── tca_query_builder.py       # SQL query builders (库/表缺失 → 降级空结果, 009)
│   ├── tca_utils.py               # pure functions (date/time, cohort, scorecard)
│   ├── tca_cache.py               # query result cache (Redis; 连接失败 → 降级直查)
│   ├── query_cli.py               # QueryEngine 类（CLI 命令分发目标）
│   ├── __main__.py                # CLI 入口：python -m CostView.src（退出码 0/2/3，见 §4.2）
│   └── monitoring/                # bdib_health · metric_coverage · report_aggregator · report_dims ·
│                                  # anomaly_query · tca_report_html · time_range
├── tests/                          # 7 个测试文件，213 个测试函数（pytest 收集 219 个用例：
│                                   #   test_report_metrics 105 / test_monitoring 57 /
│                                   #   test_tca_query_service 27 / test_data_freshness 11 /
│                                   #   test_order_aggregation 9 /
│                                   #   test_cli_entrypoint 3（参数化展开 9）/
│                                   #   test_golden_samples 1）
├── scripts/                        # golden 基线生成（gen_golden.py / make_golden_snapshot.py）
# 注：data.migrated.<ts>/ 为 2026-09-02 数据迁移的本地留证目录，已被 .gitignore 忽略
#     （匹配规则 `CostView/data.migrated.*/`），从不入版本库；释放磁盘需人工确认后再删除
```

> **数据根（唯一来源）**：`${EMSXVIEW_DATA_DIR}` 环境变量 > 默认 `D:\db`（`data_access/config.Config.DEFAULT_DATA_DIR`）。库/表常量唯一来源 `data_access/config.py`，禁止在本模块硬编码。
> **数据更新触发**（010-extract-pipeline）：`platform_data/pipeline_jobs.py`（`trigger_pipeline` / `get_job`）与 `/api/tca/trigger-update`、`/api/db/update` 端点已移除；数据更新维护的唯一写入方是独立仓库 EMSXDataPipeline，经 backend 鉴权代理（`POST /api/tca/runner/run` / `GET /api/tca/runner/status`，`backend/api/routers/costview.py`）转发至其 Runner（`POST /run`、`GET /status`，本机 `:8100`，单任务模型，重复触发返回 409 幂等受理）。

## Deployment

### Standalone (microservice mode)
```bash
cd CostView
pip install -e .                    # Install emsxview-costview package
cd api
pip install -r requirements.txt
python main.py                      # Starts on :8002
```

### 路由桥接（backend 单进程内访问 TCA）
```bash
# backend/api/main.py 经 EMSXVIEW_OPTIONAL_MODULES（默认 costview:CostView）挂载
# /api/tca/* 到 core :3000，前端单入口访问，无需单独启动 :8002
cd backend/api
python main.py
```

## Endpoints

共 13 个端点（8 个 costview 路由 + 5 个 monitoring 路由），行号取自 `api/routers/` 源码（2026-09-15 复核）：

| Endpoint | Description | Source |
|----------|-------------|--------|
| `POST /api/tca/analyze` | Run TCA analysis with optional filters (route 级，读 `tca_route_summary`) | `api/routers/costview.py:143` |
| `POST /api/tca/analyze-orders` | TCA order-aggregate query（`TCA_ORDER_AGG_ENABLED` 默认关闭） | `api/routers/costview.py:215` |
| `POST /api/tca/scorecard` | Broker/strategy cohort scorecard | `api/routers/costview.py:314` |
| `POST /api/tca/recommendations/pin` | Pin a broker recommendation handoff（ExecutionView 经 `GET /api/broker-recommendations` 读取） | `api/routers/costview.py:396` |
| `GET /api/tca/handoff/post-trade/{order_id}` | Peek ExecutionView → CostView handoff | `api/routers/costview.py:442` |
| `GET /api/tca/data-freshness` | TCA 数据新鲜度（最新交易日 / 滞后工作日数） | `api/routers/costview.py:491` |
| `GET /api/tca/capabilities` | 当前可见的区间 / 维度 / 指标能力清单 | `api/routers/costview.py:545` |
| `GET /api/costview/regime-distribution` | Per-day regime label counts | `api/routers/costview.py:584` |
| `GET /api/tca/monitoring/bdib-health` | BDIB data health scan | `api/routers/monitoring.py:151` |
| `GET /api/tca/monitoring/metric-coverage` | Computed-metric non-NULL coverage | `api/routers/monitoring.py:187` |
| `GET /api/tca/monitoring/report-summary` | TCA report aggregation (KPI/charts/rankings) | `api/routers/monitoring.py:225` |
| `GET /api/tca/monitoring/anomaly-thresholds` | Anomaly route-filter thresholds | `api/routers/monitoring.py:269` |
| `GET /api/tca/monitoring/export-html` | One-click self-contained HTML report download | `api/routers/monitoring.py:288` |

> 报告口径缺陷清单见 [`docs/report-tca-known-limitations.md`](../docs/report-tca-known-limitations.md)（§一 硬缺口 / §三 口径脚注）。

## 不做什么（职责边界）

- **不触发 ETL**：数据更新唯一写入方是独立仓库 EMSXDataPipeline；触发链路（含失败与幂等语义）见主 [README.md §3.2](../README.md#32-etl-触发链跨仓库costview-是只读消费者)。
- **不写任何数据库**：全部经 `data_access` 只读连接（`mode=ro`），WRITE/admin tier 请求被拒绝。
- **不直连 Bloomberg**：无 blpapi 依赖。
- **不重复实现 ETL 入口**：`src/__main__.py` + `src/query_cli.py` 仅为只读巡检 CLI（见下方 §CLI），不承担任何数据写入职责。

## CLI（只读巡检）

```bash
# 仓库根执行；退出码 0=成功 / 2=数据源不可用 / 3=结果为空且加了 --fail-on-empty
python -m CostView.src --query fills      --date 20260408
python -m CostView.src --query summary    --date 20260408 --output json
python -m CostView.src --query raw-fills  --order-id 12345
python -m CostView.src --query log        --last 10
python -m CostView.src --query tickers    --ticker-type equ_ticker
```

> `--query` 取值：`fills` / `raw-fills` / `log` / `order-log` / `orders` / `tickers` / `summary`。入口由 `tests/test_cli_entrypoint.py` 锁定，详见主 [README.md §4.2](../README.md)。

## Verification

```bash
# 运行单元测试（7 个测试文件，213 个测试函数，pytest 收集 219 个用例）
python -m pytest CostView/tests/

# 黄金样本回归（口径漂移硬阻断；缺 golden 基线/冻结快照时自动 skip）
python -m pytest CostView/tests/test_golden_samples.py -v

# 覆盖率（未设门槛，仅观测）
python -m pytest CostView/tests/ --cov=CostView/src --cov=CostView/api --cov-report=term-missing

# 健康启动验证（standalone 模式）
cd CostView/api && python main.py    # Swagger: http://<host>:<COSTVIEW_PORT>/docs
```

## Dependencies

包级依赖声明在 `pyproject.toml`（`pip install -e .`）：`pydantic`、`pandas`、`emsxview-platform-data`、`emsxview-datapipeline`。
微服务进程依赖见 `api/requirements.txt`（fastapi / uvicorn / redis 等）。

- `data_access/`（仓库内只读数据访问层，非独立 pip 包）
- Redis (for cross-process handoff in microservice mode + query cache；缓存连接失败自动降级直查)
- No Bloomberg EMSX session required
- No PostgreSQL required (SQLite only)

## Nginx Routing

```nginx
location /api/tca/ {
    proxy_pass <COSTVIEW_BASE_URL>/api/tca/;   # 默认 http://localhost:8002，环境变量 COSTVIEW_HOST / COSTVIEW_PORT
}
```

---

*Status: Independent microservice with Redis handoff to main EMSXView service.*
*Last updated: 2026-09-15（成本次冗余清理：移除 secure_config 等 FillFetch 遗产记录、补齐端点表 `data-freshness` / `capabilities`、重写成熟度论据、修正 CLI 状态）*
*Last verified: 2026-09-15（端点清单与行号提取自 `api/routers/` 源码；测试计数经 grep `def test_` 统计并与 pytest 实际收集数比对；`python -m pytest CostView/tests/` 实测 217 passed。**未做运行时验证**——服务启动响应、端口连通性与查询延迟未在本轮测量）*
