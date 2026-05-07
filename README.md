# EMSX Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis and post-trade analytics**

---

## Architecture Overview

The EMSX Trading Platform converges on one frontend shell, three business modules, and one logical data domain that covers the full trade lifecycle:

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                           EMSX Trading Platform                              â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚                                                                             â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”      â”‚
â”‚  â”‚   MarketView     â”‚â”€â”€â”€â–¶â”‚   ExecutionView  â”‚â”€â”€â”€â–¶â”‚    CostView      â”‚      â”‚
â”‚  â”‚  (Pre-Trade)     â”‚    â”‚  (Order Exec)    â”‚    â”‚  (Post-Trade)    â”‚      â”‚
â”‚  â”‚                  â”‚    â”‚                  â”‚    â”‚                  â”‚      â”‚
â”‚  â”‚ â€¢ Market Data    â”‚    â”‚ â€¢ Order Mgmt     â”‚    â”‚ â€¢ TCA Analysis   â”‚      â”‚
â”‚  â”‚ â€¢ Pre-trade Risk â”‚    â”‚ â€¢ Route Mgmt     â”‚    â”‚ â€¢ Performance    â”‚      â”‚
â”‚  â”‚ â€¢ Analytics      â”‚    â”‚ â€¢ EMSX API       â”‚    â”‚ â€¢ Reporting      â”‚      â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜      â”‚
â”‚           â”‚                       â”‚                       â”‚                â”‚
â”‚           â–¼                       â–¼                       â–¼                â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚
â”‚  â”‚        Shared frontend shell + logical data/infrastructure          â”‚   â”‚
â”‚  â”‚ ExecutionView/frontend Â· CostView/src Â· platform_data Â· docs/      â”‚   â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚
â”‚                                                                             â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

Current implementation status:

- **`ExecutionView/frontend`** is the active platform shell. It mounts the **Execution** workspace, **CostView** module, and **MarketView** anchor.
- **`ExecutionView/backend/api`** is the active backend assembly layer with routers/services/repositories.
- **`CostView/src`** is the active post-trade data and analytics domain. Its canonical UI lives in the frontend shell under `ExecutionView/frontend/src/modules/costview/`.
- **`MarketView/`** has a shell anchor and a read-only market snapshot endpoint (`/api/marketview/snapshot`). Domain capabilities are being built incrementally.
- **`platform_data/`** provides the shared adapter layer for the logical data domain, bridging operational and analytical data.

## Module Descriptions

### MarketView (`MarketView/`)
**Pre-Trade Analysis Module**

Provides market data analysis, instrument screening, and trade decision support.

- Market snapshot (daily close, volatility, volume, ADV)
- Instrument scanning and filtering
- Pre-trade risk assessment
- Market impact estimation
- Optimal timing recommendations

**Status:** ðŸŸ¡ Shell anchor and snapshot API in place â€” domain capabilities being built incrementally

---

### ExecutionView (`ExecutionView/`)
**Order Execution Module**

The core trading execution engine with Bloomberg EMSX API integration.

**Frontend:** React 19 + TypeScript + Vite + Tailwind CSS
- Order and route management UI
- Real-time monitoring dashboard
- Batch operations
- Broker algorithm configuration
- Modular architecture (MarketView / Execution / CostView tabs)

**Backend:** Python 3.11 + FastAPI + Pydantic v2 + blpapi
- Order/Route CRUD operations
- WebSocket real-time updates
- JWT authentication
- Bloomberg EMSX API integration

**Status:** ðŸŸ¢ Production-ready core module inside the active frontend shell

---

### CostView (`CostView/`)
**Post-Trade Analysis Module**

Transaction cost analysis, performance reporting, and execution quality metrics.

- **FillFetch** â€” automated EMSX fill retrieval with SHA-256 deduplication
- Implementation Shortfall (IS) calculations
- VWAP/TWAP benchmark analysis
- Execution quality metrics
- Performance reporting dashboards
- Cost attribution analysis

**Status:** ðŸŸ¢ Active post-trade module â€” data pipeline in `CostView/src/`, UI integrated into the frontend shell

---

## Directory Structure

```
EMSX/
â”œâ”€â”€ README.md                      # This file
â”œâ”€â”€ QUICKSTART.md                  # One-command quick start guide
â”œâ”€â”€ package.json                   # Root package manifest
â”œâ”€â”€ start-services.bat             # Interactive Windows service launcher
â”œâ”€â”€ MarketView/
â”‚   â””â”€â”€ README.md                  # Pre-trade module contract and docs
â”œâ”€â”€ ExecutionView/
â”‚   â”œâ”€â”€ README.md                  # Execution module documentation
â”‚   â”œâ”€â”€ frontend/                  # Active React shell for platform modules
â”‚   â”‚   â””â”€â”€ src/
â”‚   â”‚       â”œâ”€â”€ sections/          # Execution workspace (OrderTable, RouteTable, etc.)
â”‚   â”‚       â”œâ”€â”€ modules/
â”‚   â”‚       â”‚   â”œâ”€â”€ marketview/    # Pre-trade shell anchor
â”‚   â”‚       â”‚   â””â”€â”€ costview/      # Post-trade integrated UI
â”‚   â”‚       â”œâ”€â”€ services/          # API clients
â”‚   â”‚       â”œâ”€â”€ hooks/             # React hooks
â”‚   â”‚       â””â”€â”€ types/             # TypeScript definitions
â”‚   â””â”€â”€ backend/
â”‚       â””â”€â”€ api/                   # Active FastAPI assembly layer
â”‚           â”œâ”€â”€ main.py            # Application entry point
â”‚           â”œâ”€â”€ routers/           # HTTP/WebSocket routers
â”‚           â”œâ”€â”€ services/          # Business logic
â”‚           â”œâ”€â”€ repositories/      # Data access
â”‚           â””â”€â”€ models/            # Persistence schemas
â”œâ”€â”€ CostView/
â”‚   â”œâ”€â”€ README.md                  # CostView module documentation
â”‚   â”œâ”€â”€ requirements.txt           # Python dependencies
â”‚   â”œâ”€â”€ src/                       # Active post-trade data pipeline and query services
â”‚   â”‚   â”œâ”€â”€ pipeline.py            # Data ingestion pipeline
â”‚   â”‚   â”œâ”€â”€ tca_query_service.py   # TCA analytical queries
â”‚   â”‚   â”œâ”€â”€ fill_fetch.py          # EMSX fill fetcher
â”‚   â”‚   â””â”€â”€ ...
â”‚   â”œâ”€â”€ tests/                     # Unit tests
â”‚   â”œâ”€â”€ data/                      # Pipeline data stores
â”‚   â””â”€â”€ frontend/                  # Legacy prototype UI (non-canonical)
â”œâ”€â”€ platform_data/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ adapters.py                # Shared logical data-domain adapters
â”‚   â””â”€â”€ repositories.py            # Cross-domain data repositories
â”œâ”€â”€ docs/                          # Project documentation
â”‚   â”œâ”€â”€ PROJECT_STRUCTURE.md       # Canonical architecture reference
â”‚   â”œâ”€â”€ DATA_DOMAIN.md             # Data domain documentation
â”‚   â”œâ”€â”€ SERVICE_MANAGEMENT.md      # Service operations guide
â”‚   â””â”€â”€ ...
â”œâ”€â”€ scripts/                       # Shared automation and utility scripts
â”‚   â”œâ”€â”€ service-manager.ps1        # PowerShell service manager
â”‚   â”œâ”€â”€ start-all.bat / stop-all.bat
â”‚   â””â”€â”€ ...
â”œâ”€â”€ data/                          # Shared runtime data
â””â”€â”€ logs/                          # Service logs
```

> Older one-off scripts and exploratory notebooks are kept under
> `docs/archive/<date>/`, `scripts/_archive/<date>/`, and
> `CostView/_archive/<date>/`. See `docs/archive/2026-04-28/README.md`
> for the most recent cleanup.

## Quick Start

For a one-command start on Windows, see [**QUICKSTART.md**](./QUICKSTART.md).

### Prerequisites
- Docker Desktop â‰¥ 4.x
- Bloomberg Terminal (with API enabled)
- Node.js 20+ (for frontend development)
- Python 3.11+ (for backend development)

### Run ExecutionView Module (Production)

```bash
cd ExecutionView/backend

# Configure environment
cp .env.example .env
# Edit .env and set JWT_SECRET

# Start all services
docker compose up -d
```

Access points:
- Frontend: http://localhost
- API Docs: http://localhost/api/docs
- Health Check: http://localhost/api/health

### Frontend Development (Mock Mode)

```bash
cd ExecutionView/frontend
npm install
npm run dev    # http://localhost:5173
```

## Module Interactions

```
MarketView â”€â”€â”€â”€â”€â”€â–¶ ExecutionView â”€â”€â”€â”€â”€â”€â–¶ CostView
    â”‚                      â”‚                    â”‚
    â”‚  Market Data         â”‚  Orders/Routes     â”‚  TCA Reports
    â”‚  Analytics           â”‚  Executions        â”‚  Performance
    â”‚  Risk Data           â”‚  Fill Events       â”‚  Metrics
    â”‚                      â”‚                    â”‚
    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
              Shared Services Layer
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript 5.9, Vite 7, Tailwind CSS 3.4 |
| UI Components | shadcn/ui, Radix UI |
| Visualization | Recharts |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Bloomberg API | blpapi 3.23 |
| Auth | JWT (python-jose, passlib) |
| Cache | Redis 7 |
| Proxy | Nginx 1.27 |
| Monitoring | Prometheus + Grafana |
| Data | SQLite (analytical), PostgreSQL (operational, optional) |
| Deployment | Docker Compose |
| Scripts | PowerShell, Batch, Python |

## Contributing

1. Each module should be self-contained with its own README
2. Shared code goes in the root `scripts/` folder
3. Module-specific documentation goes in `docs/`
4. API documentation goes in `ExecutionView/backend/README.md`

## Related Documentation

| Document | Purpose |
|----------|---------|
| [QUICKSTART.md](./QUICKSTART.md) | One-command Windows service launcher |
| [docs/spec/project-structure.md](./docs/spec/project-structure.md) | Canonical architecture reference |
| [docs/spec/data-domain.md](./docs/spec/data-domain.md) | Logical data domain design |
| [docs/ops/service-management.md](./docs/ops/service-management.md) | Service operations and troubleshooting |
| [ExecutionView/README.md](./ExecutionView/README.md) | Execution module details |
| [CostView/README.md](./CostView/README.md) | CostView module details |
| [MarketView/README.md](./MarketView/README.md) | MarketView module details |
| [é¡¹ç›®åŠŸèƒ½æž„å»ºè§„åˆ’.md](./é¡¹ç›®åŠŸèƒ½æž„å»ºè§„åˆ’.md) | ä¸‹ä¸€æ­¥åŠŸèƒ½æž„å»ºè·¯çº¿å›¾ (ä¸­æ–‡) |

---

*Last updated: April 28, 2026*

