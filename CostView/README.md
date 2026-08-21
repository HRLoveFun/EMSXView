# CostView Module

> **Post-Trade TCA Analytics** · 🟢 Independent Microservice (port 8002)

---

## Overview

The **CostView** module provides post-trade TCA (Transaction Cost Analysis)
and broker recommendation services. It now runs as an independent FastAPI service.

## Architecture

```
CostView/                          # CostView domain
├── pyproject.toml                 # Pip package (emsxview-costview)
├── api/                           # Independent microservice
│   ├── main.py                    # FastAPI app entry (:8002)
│   ├── config.py                  # Service configuration
│   ├── requirements.txt           # Python dependencies
│   └── routers/
│       ├── costview.py            # TCA analysis endpoints (/api/tca/*)
│       └── monitoring.py          # Monitoring endpoints (/api/tca/monitoring/*)
├── src/
│   ├── tca_query_service.py       # TCA query orchestrator
│   ├── tca_query_builder.py       # SQL query builders (tca_route_summary)
│   ├── tca_utils.py               # pure functions (date/time, cohort, scorecard)
│   ├── tca_cache.py               # query result cache
│   ├── query_cli.py               # CLI query tool
│   ├── secure_config.py           # encrypted config
│   └── monitoring/                # BDIB health, metric coverage, report aggregation
├── data/                           # SQLite databases (paths via DataPipeline.config)
│   ├── raw_fills.db                # raw fills
│   ├── processed_fills.db          # cleaned/processed fills
│   ├── raw_bdib.db                 # raw BDIB bars
│   ├── fill_bdib.db                # integrated fill+BDIB (+ tca_route_summary)
│   ├── regime.db                   # regime classification + attribution
│   ├── execution_history.db        # execution history
│   ├── ticker_registry.db          # ticker registry
│   └── fill_fetch_history.db       # fetch audit
├── tests/                          # CostView unit/integration tests
└── scripts/                        # Maintenance scripts
```

> Pipeline job registry (`trigger_pipeline` / `get_job`) 位于
> `platform_data/pipeline_jobs.py`，被 CostView `/api/tca/trigger-update` 与
> DatabaseView `/api/db/update` 共享。

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

| Endpoint | Description |
|----------|-------------|
| `POST /api/tca/analyze` | Run TCA analysis with optional filters |
| `POST /api/tca/scorecard` | Broker/strategy cohort scorecard |
| `POST /api/tca/trigger-update` | Manually start daily update pipeline |
| `GET /api/tca/update-status/{job_id}` | Poll a triggered pipeline job |
| `POST /api/tca/recommendations/pin` | Pin a broker recommendation handoff |
| `GET /api/tca/handoff/post-trade/{order_id}` | Peek ExecutionView → CostView handoff |
| `GET /api/costview/regime-distribution` | Per-day regime label counts |
| `GET /api/tca/monitoring/bdib-health` | BDIB data health scan |
| `GET /api/tca/monitoring/metric-coverage` | Computed-metric non-NULL coverage |
| `GET /api/tca/monitoring/report-summary` | TCA report aggregation (KPI/charts/rankings) |
| `GET /api/tca/monitoring/export-html` | One-click self-contained HTML report download |

> 报告口径缺陷清单见 `docs/report-tca-known-limitations.md`。

## Dependencies

- `emsxview-platform-data` (pip editable install)
- `emsxview-costview` (self, pip editable install)
- Redis (for cross-process handoff in microservice mode)
- No Bloomberg EMSX session required
- No PostgreSQL required (SQLite only)

## Nginx Routing

```nginx
location /api/tca/ {
    proxy_pass http://localhost:8002/api/tca/;
}
```

---

*Status: Independent microservice with Redis handoff to main EMSXView service.*
