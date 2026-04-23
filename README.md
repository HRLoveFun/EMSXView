# EMSX Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis and post-trade analytics**

---

## Architecture Overview

The EMSX Trading Platform is evolving toward one frontend shell, three business modules, and one logical data domain that covers the full trade lifecycle:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           EMSX Trading Platform                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐      │
│  │   MarketView     │───▶│    Execution     │───▶│    CostView      │      │
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
│  │  Execution/frontend · CostView/src · docs/ · scripts/ · data/      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

Current implementation status:

- `Execution/frontend` is the active platform shell and currently mounts `Execution`, `CostView`, and a `MarketView` anchor.
- `Execution/backend/api` is the active backend assembly layer with routers/services/repositories, not a single all-in-one runtime file anymore.
- `CostView/src` is the active post-trade data and analytics domain. Its canonical UI now lives in the frontend shell under `Execution/frontend/src/modules/costview/`.
- `MarketView/` is still an early module contract, but the shell anchor now exists for incremental build-out.

## Module Descriptions

### MarketView (`MarketView/`)
**Pre-Trade Analysis Module**

Provides market data analysis, instrument screening, and trade decision support.

- Market data visualization
- Instrument scanning and filtering
- Pre-trade risk assessment
- Market impact estimation
- Optimal timing recommendations

**Status:** 🟡 Shell anchor in place - domain capabilities pending

---

### Execution (`Execution/`)
**Order Execution Module**

The core trading execution engine with Bloomberg EMSX API integration.

**Frontend:** React 19 + TypeScript + Vite + Tailwind CSS
- Order and route management UI
- Real-time monitoring dashboard
- Batch operations
- Broker algorithm configuration

**Backend:** Python 3.11 + FastAPI + blpapi
- Order/Route CRUD operations
- WebSocket real-time updates
- JWT authentication
- Bloomberg EMSX API integration

**Status:** 🟢 Production-ready core module inside the active frontend shell

---

### CostView (`CostView/`)
**Post-Trade Analysis Module**

Transaction cost analysis, performance reporting, and execution quality metrics.

- Implementation Shortfall (IS) calculations
- VWAP/TWAP benchmark analysis
- Execution quality metrics
- Performance reporting dashboards
- Cost attribution analysis

**Status:** 🟢 Active post-trade module - data pipeline in `CostView/`, UI integrated into the frontend shell

---

## Directory Structure

```
EMSX/
├── README.md
├── MarketView/                           # Pre-trade module contract and docs
├── Execution/
│   ├── frontend/                         # Active React shell for platform modules
│   │   └── src/
│   │       └── modules/
│   │           ├── marketview/
│   │           └── costview/
│   └── backend/
│       └── api/                          # Active FastAPI routers/services/repositories
├── CostView/
│   ├── src/                              # Active post-trade data pipeline and query services
│   ├── scripts/
│   ├── data/
│   └── frontend/                         # Legacy prototype UI, pending archive/consolidation
├── docs/
├── scripts/
├── data/
└── logs/
```

## Quick Start

### Prerequisites
- Docker Desktop ≥ 4.x
- Bloomberg Terminal (with API enabled)
- Node.js 20+ (for frontend development)
- Python 3.11+ (for backend development)

### Run Execution Module (Production)

```bash
cd Execution/backend

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
cd Execution/frontend
npm install
npm run dev    # http://localhost:5173
```

## Module Interactions

```
MarketView ───────▶ Execution ───────▶ CostView
    │                    │                   │
    │  Market Data       │  Orders/Routes    │  TCA Reports
    │  Analytics         │  Executions       │  Performance
    │  Risk Data         │  Fill Events      │  Metrics
    │                    │                   │
    └────────────────────┴───────────────────┘
              Shared Services Layer
```

## Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 19, TypeScript 5.9, Vite 7, Tailwind CSS 3.4 |
| UI Components | shadcn/ui, Radix UI |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| Bloomberg API | blpapi 3.23 |
| Auth | JWT (python-jose, passlib) |
| Cache | Redis 7 |
| Proxy | Nginx 1.27 |
| Monitoring | Prometheus + Grafana |
| Deployment | Docker Compose |

## Contributing

1. Each module should be self-contained with its own README
2. Shared code goes in the root `scripts/` or `config/` folders
3. Module-specific documentation goes in `docs/features/`
4. API documentation goes in `docs/reference/`

## Migration Notes

If you're coming from the previous project structure, see [MIGRATION.md](./MIGRATION.md) for a complete mapping of old to new paths.

---

*Last updated: March 23, 2026*
