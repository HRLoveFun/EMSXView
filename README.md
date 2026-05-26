# EMSX Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis and post-trade analytics**

---

## Architecture Overview

The EMSX Trading Platform converges on one frontend shell, three business modules, and one logical data domain that covers the full trade lifecycle:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EMSX Trading Platform                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐      │
│  │   MarketView     │───▶│   ExecutionView  │───▶│    CostView      │      │
│  │  (Pre-Trade)     │    │  (Order Exec)    │    │  (Post-Trade)    │      │
│  │                  │    │                  │    │                  │      │
│  │ • Market Data    │    │ • Order Mgmt     │    │ • TCA Analysis   │      │
│  │ • Pre-trade Risk │    │ • Route Mgmt     │    │ • Performance    │      │
│  │ • Analytics      │    │ • EMSX API       │    │ • Reporting      │      │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘      │
│           │                       │                       │                │
│           ▼                       ▼                       ▼                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │        Shared frontend shell + logical data/infrastructure          │   │
│  │ ExecutionView/frontend · CostView/src · platform_data · docs/      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
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

**Status:** 🟡 Shell anchor and snapshot API in place — domain capabilities being built incrementally

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

**Status:** 🟢 Production-ready core module inside the active frontend shell

---

### CostView (`CostView/`)
**Post-Trade Analysis Module**

Transaction cost analysis, performance reporting, and execution quality metrics.

- **FillFetch** — automated EMSX fill retrieval with SHA-256 deduplication
- Implementation Shortfall (IS) calculations
- VWAP/TWAP benchmark analysis
- Execution quality metrics
- Performance reporting dashboards
- Cost attribution analysis

**Status:** 🟢 Active post-trade module — data pipeline in `CostView/src/`, UI integrated into the frontend shell

---

## Directory Structure

```
EMSX/
├── README.md                      # This file
├── QUICKSTART.md                  # One-command quick start guide
├── 重启服务.bat                   # One-click restart
├── MarketView/
│   └── README.md                  # Pre-trade module contract and docs
├── ExecutionView/
│   ├── README.md                  # Execution module documentation
│   ├── frontend/                  # Active React shell for platform modules
│   │   └── src/
│   │       ├── modules/
│   │       │   ├── execution/     # Order/Route management workspace
│   │       │   ├── costview/      # Post-trade TCA UI
│   │       │   ├── marketview/    # Pre-trade shell anchor
│   │       │   └── databaseview/  # Database admin UI
│   │       ├── app/               # Shell layout, toolbar, hooks
│   │       ├── shared/            # Cross-module hooks, lib, services, types
│   │       └── components/        # Shared React components
│   └── backend/
│       └── api/                   # Active FastAPI assembly layer
│           ├── main.py            # Application entry point
│           ├── routers/           # HTTP/WebSocket routers
│           ├── services/          # Business logic
│           ├── repositories/      # Data access
│           └── models/            # Persistence schemas
├── CostView/
│   ├── README.md                  # CostView module documentation
│   ├── requirements.txt           # Python dependencies
│   ├── src/                       # TCA query service and CLI
│   │   ├── tca_query_service.py   # TCA analytical queries
│   │   ├── tca_query_builder.py   # TCA query builder
│   │   ├── query_cli.py           # CLI query interface
│   │   └── ...
│   ├── tests/                     # Unit tests
│   ├── data/                      # Pipeline data stores
│   └── frontend/                  # Legacy prototype UI (non-canonical)
├── platform_data/
│   ├── __init__.py
│   ├── adapters.py                # Cross-domain data adapters
│   ├── execution_history_service.py  # Historical execution queries
│   └── database_diagnostics.py    # DB diagnostics utility
├── docs/                          # Project documentation
│   ├── spec/                      # Architecture specs
│   │   ├── project-structure.md   # Canonical architecture reference
│   │   ├── data-domain.md         # Data domain documentation
│   │   └── memory.md              # Architecture memory & constraints
│   ├── ops/                       # Operations docs
│   │   └── service-management.md  # Service operations guide
│   ├── roadmap/                   # Roadmap & WBS
│   └── ...
├── scripts/                       # Shared automation and utility scripts
│   ├── ops/service-manager.ps1    # PowerShell service manager
│   ├── start-all.bat / stop-all.bat
│   └── ...
├── data/                          # Shared runtime data
└── logs/                          # Service logs
```

> Older one-off scripts and exploratory notebooks are kept under
> `docs/archive/<date>/`, `scripts/_archive/<date>/`, and
> `CostView/_archive/<date>/`. See `docs/archive/2026-04-28/README.md`
> for the most recent cleanup.

## Quick Start

For a one-command start on Windows, see [**QUICKSTART.md**](./QUICKSTART.md).

### Prerequisites
- Docker Desktop ≥ 4.x
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
MarketView ──────▶ ExecutionView ──────▶ CostView
    │                      │                    │
    │  Market Data         │  Orders/Routes     │  TCA Reports
    │  Analytics           │  Executions        │  Performance
    │  Risk Data           │  Fill Events       │  Metrics
    │                      │                    │
    └──────────────────────┴────────────────────┘
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

---

*Last updated: May 26, 2026*

