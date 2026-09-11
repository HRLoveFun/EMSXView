# CostView Module

> **Post-Trade TCA Analytics** · 🟡 **Beta** · Independent Microservice (port 8002)

---

## Overview

The **CostView** module provides post-trade TCA (Transaction Cost Analysis)
and broker recommendation services. It runs as an independent FastAPI service,
is a **read-only consumer** of the analytical SQLite stores (via `data_access/`,
all connections `mode=ro`), and never writes to any database.

> 成熟度分级定义见主 [README.md §0](../README.md#0-模块成熟度分级契约定义)。定级 Beta 的证据：103 个测试函数（4 个测试文件）、已知限制清单公开发布、11 个 API 端点全部可追溯到代码；欠缺：CLI 入口失效、覆盖率未量化、无黄金样本回归。

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
│   ├── query_cli.py               # QueryEngine 类（编程调用）；⚠ __main__.py 缺失，CLI 命令行入口失效
│   ├── secure_config.py           # encrypted config
│   └── monitoring/                # bdib_health · metric_coverage · report_aggregator · report_dims ·
│                                  # anomaly_query · tca_report_html · time_range
├── tests/                          # 4 个测试文件，103 个测试函数（test_monitoring 50 / test_tca_query_service 27 /
│                                   #   test_secure_config 17 / test_order_aggregation 9）
├── scripts/                        # Maintenance scripts
└── data.migrated.202609022339/     # 历史数据归档（2026-09-02 迁出）；现行数据根为 ${EMSXVIEW_DATA_DIR}
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

### Single-process (merge mode)
```bash
cd backend/api
set EMSXVIEW_MERGE_MODULES=true
python main.py                      # All modules in one process
```

## Endpoints

| Endpoint | Description | Source |
|----------|-------------|--------|
| `POST /api/tca/analyze` | Run TCA analysis with optional filters (route 级，读 `tca_route_summary`) | `api/routers/costview.py:174` |
| `POST /api/tca/analyze-orders` | TCA order-aggregate query（`TCA_ORDER_AGG_ENABLED` 默认关闭） | `api/routers/costview.py:233` |
| `POST /api/tca/scorecard` | Broker/strategy cohort scorecard | `api/routers/costview.py:289` |
| `POST /api/tca/recommendations/pin` | Pin a broker recommendation handoff（ExecutionView 经 `GET /api/broker-recommendations` 读取） | `api/routers/costview.py:362` |
| `GET /api/tca/handoff/post-trade/{order_id}` | Peek ExecutionView → CostView handoff | `api/routers/costview.py:408` |
| `GET /api/costview/regime-distribution` | Per-day regime label counts | `api/routers/costview.py:470` |
| `GET /api/tca/monitoring/bdib-health` | BDIB data health scan | `api/routers/monitoring.py:133` |
| `GET /api/tca/monitoring/metric-coverage` | Computed-metric non-NULL coverage | `api/routers/monitoring.py:169` |
| `GET /api/tca/monitoring/report-summary` | TCA report aggregation (KPI/charts/rankings) | `api/routers/monitoring.py:207` |
| `GET /api/tca/monitoring/anomaly-thresholds` | Anomaly route-filter thresholds | `api/routers/monitoring.py:251` |
| `GET /api/tca/monitoring/export-html` | One-click self-contained HTML report download | `api/routers/monitoring.py:270` |

> 报告口径缺陷清单见 [`docs/report-tca-known-limitations.md`](../docs/report-tca-known-limitations.md)（§一 硬缺口 / §三 口径脚注）。

## 不做什么（职责边界）

- **不触发 ETL**：数据更新唯一写入方是独立仓库 EMSXDataPipeline；触发链路（含失败与幂等语义）见主 [README.md §3.2](../README.md#32-etl-触发链跨仓库costview-是只读消费者)。
- **不写任何数据库**：全部经 `data_access` 只读连接（`mode=ro`），WRITE/admin tier 请求被拒绝。
- **不直连 Bloomberg**：无 blpapi 依赖。
- **CLI 命令行入口失效**：`src/__main__.py` 不存在，`python -m CostView.src` 不可用；`QueryEngine`（`src/query_cli.py`）可编程调用，恢复入口待补。

## Verification

```bash
# 运行单元测试（103 个测试函数）
python -m pytest CostView/tests/

# 健康启动验证（standalone 模式）
cd CostView/api && python main.py    # Swagger: http://localhost:8002/docs
```

## Dependencies

- `emsxview-platform-data` (pip editable install)
- `emsxview-costview` (self, pip editable install)
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
*Last verified: 2026-09-11（静态代码审计：端点清单提取自 `api/routers/` 源码行号；测试计数经 grep `def test_` 统计；未做运行时验证）*
