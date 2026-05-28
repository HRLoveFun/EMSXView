# MarketView Module

> **Pre-Trade Analysis Module** · 🟢 Independent Microservice (port 8001)

---

## Overview

The **MarketView** module provides pre-trade market snapshot and intraday
feature analysis. It now runs as an independent FastAPI service.

## Architecture

```
MarketView/                      # Independent microservice
├── main.py                      # FastAPI app entry (:8001)
├── config.py                    # Service configuration
├── requirements.txt             # Python dependencies
└── routers/
    └── marketview.py            # API endpoints

backend/api/routers/marketview.py  # Canonical copy (used in merge mode)
```

## Deployment

### Standalone (microservice mode)
```bash
cd MarketView
pip install -r requirements.txt
python main.py                    # Starts on :8001
```

### Single-process (merge mode)
```bash
cd backend/api
set EMSXVIEW_MERGE_MODULES=true
python main.py                    # All modules in one process
```

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/marketview/snapshot` | Daily market snapshot with pool/filter/sort |
| `GET /api/marketview/intraday-features` | Intraday BDIB bar features per ticker |
| `POST /api/marketview/handoff/execution` | Publish candidates to ExecutionView |

## Dependencies

- `emsxview-platform-data` (pip editable install)
- Redis (for cross-process handoff in microservice mode)
- No Bloomberg EMSX session required
- No PostgreSQL required

## Data Flow

```
bdib_daily_summary (SQLite)
  → platform_data/adapters.py (MarketReferenceDataAdapter)
    → MarketView/router/marketview.py (FastAPI endpoint)
      → frontend/src/modules/marketview/MarketViewModule.tsx (UI)
```

## Nginx Routing

```nginx
location /api/marketview/ {
    proxy_pass http://localhost:8001/api/marketview/;
}
```

---

*Status: Independent microservice with Redis handoff to main EMSXView service.*
