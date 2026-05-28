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
│       ├── costview.py            # TCA analysis endpoints
│       └── _pipeline_jobs.py      # Pipeline trigger (subprocess)
├── src/
│   └── tca_query_service.py       # TCA query logic
├── data/                           # SQLite databases
│   ├── processed_fills.db
│   ├── fill_bdib.db
│   └── bdib_daily_summary.db
└── scripts/                        # Maintenance scripts
```

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
| `POST /api/tca/trigger-update` | Manually start daily update pipeline |
| `GET /api/tca/update-status/{job_id}` | Poll a triggered pipeline job |
| `POST /api/tca/recommendations/pin` | Pin a broker recommendation handoff |
| `GET /api/tca/recommendations` | List pinned recommendations |

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
