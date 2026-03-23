# EMSX Trading Platform

> **Enterprise-grade execution management system with pre-trade analysis and post-trade analytics**

---

## Architecture Overview

The EMSX Trading Platform is organized into three core modules that cover the complete trade lifecycle:

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
│  │                     Shared Infrastructure                            │   │
│  │  docs/ · scripts/ · config/ · tests/ · data/                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Module Descriptions

### MarketView (`MarketView/`)
**Pre-Trade Analysis Module**

Provides market data analysis, instrument screening, and trade decision support.

- Market data visualization
- Instrument scanning and filtering
- Pre-trade risk assessment
- Market impact estimation
- Optimal timing recommendations

**Status:** 🟡 Placeholder - Ready for development

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

**Status:** 🟢 Production Ready

---

### CostView (`CostView/`)
**Post-Trade Analysis Module**

Transaction cost analysis, performance reporting, and execution quality metrics.

- Implementation Shortfall (IS) calculations
- VWAP/TWAP benchmark analysis
- Execution quality metrics
- Performance reporting dashboards
- Cost attribution analysis

**Status:** 🟡 Placeholder - Ready for development

---

## Directory Structure

```
EMSX/
├── README.md                 # This file
├── MIGRATION.md              # Migration guide from old structure
│
├── MarketView/               # Pre-trade analysis module
│   └── README.md
│
├── Execution/                # Order execution module (existing code)
│   ├── README.md
│   ├── frontend/             # React application
│   │   ├── src/
│   │   ├── public/
│   │   ├── package.json
│   │   └── Dockerfile
│   └── backend/              # FastAPI application
│       ├── api/              # Python backend code
│       ├── config/           # Nginx, Prometheus configs
│       ├── docker-compose.yml
│       └── .env.example
│
├── CostView/                 # Post-trade analysis module
│   └── README.md
│
├── docs/                     # Consolidated documentation
│   ├── ERROR_PATTERNS.md
│   ├── USER_GUIDE.md
│   ├── FRONTEND_UI_DESCRIPTION.md
│   ├── reference/            # API references
│   └── features/             # Feature specifications
│
├── scripts/                  # Utility and deployment scripts
│   ├── deploy/               # Deployment scripts
│   └── diagnose/             # Diagnostic tools
│
├── config/                   # Shared configuration files
│
├── tests/                    # Test suites
│
├── data/                     # Reference data
│
└── archive/                  # Archived documentation
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
