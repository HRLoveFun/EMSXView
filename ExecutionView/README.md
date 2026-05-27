# ExecutionView Module

> **Order Execution Module** · 🟢 Production-ready
> Order and route management with Bloomberg EMSX API integration

---

## Overview

The **ExecutionView** module is the core trading execution engine of the EMSXView platform. It provides comprehensive order and route management capabilities through integration with the Bloomberg EMSX API.

## Architecture

```
ExecutionView/
├── frontend/              # React-based trading UI
│   ├── src/
│   │   ├── components/    # React components (dialogs, UI)
│   │   ├── sections/      # Page sections (OrderTable, RouteTable, etc.)
│   │   ├── services/      # API client services
│   │   ├── hooks/         # Custom React hooks
│   │   ├── lib/           # Utility libraries
│   │   └── types/         # TypeScript type definitions
│   ├── public/            # Static assets
│   └── Dockerfile         # Container build
│
└── backend/               # Python FastAPI backend
    ├── api/               # FastAPI application (main.py, auth.py)
    ├── config/            # Nginx, Prometheus configs
    ├── logs/              # Runtime logs
    └── docker-compose.yml # Container orchestration
```

## Frontend (React + TypeScript + Vite)

### Key Components

| Component | Purpose |
|-----------|---------|
| `OrderTable.tsx` | Order listing with filtering and grouping |
| `RouteTable.tsx` | Route management with actions |
| `ExecutionBoard.tsx` | Main trading dashboard |
| `MonitorBoard.tsx` | Alert conditions and flagged orders |
| `BatchOperationPanel.tsx` | Bulk order modifications |
| `SettingsBoard.tsx` | Broker algorithm configuration |

### Technology Stack
- React 19 + TypeScript 5.9
- Vite 7 (build tool)
- Tailwind CSS 3.4 (styling)
- shadcn/ui + Radix UI (components)
- Recharts (visualization)

### Build & Run
```bash
cd ExecutionView/frontend
npm install
npm run dev        # Development server
npm run build      # Production build
```

## Backend (Python + FastAPI)

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/auth/login` | POST | JWT authentication |
| `/api/orders` | GET | List orders |
| `/api/orders/batch-update` | POST | Bulk modify orders |
| `/api/orders/modify` | POST | Modify single order |
| `/api/orders/route` | POST | Create route |
| `/api/routes` | GET | List routes |
| `/api/routes/cancel` | POST | Cancel route |
| `/api/routes/modify` | POST | Modify route |
| `/api/brokers` | GET | List brokers |
| `/api/connection` | GET | Bloomberg connection status |
| `/ws/orders` | WebSocket | Real-time order updates |

### Technology Stack
- Python 3.11
- FastAPI 0.109 + Pydantic v2
- blpapi 3.23 (Bloomberg API)
- JWT authentication (python-jose)
- Redis (caching)

### Run with Docker
```bash
cd ExecutionView/backend
# Configure environment
cp .env.example .env
# Edit .env with your settings

# Start services
docker compose up -d
```

## Environment Variables

### Frontend
- `VITE_API_URL` - Backend API URL (empty for mock mode)

### Backend
- `JWT_SECRET` - JWT signing key (required)
- `ALLOWED_TRADERS` - Comma-separated trader whitelist
- `BLOOMBERG_HOST` - Bloomberg Terminal host
- `BLOOMBERG_PORT` - Bloomberg API port (default: 8194)

## Integration Points

### Receives data from:
- **Bloomberg Terminal** - Order/route data via EMSX API
- **MarketView** (future) - Market data for order enrichment

### Sends data to:
- **CostView** (future) - ExecutionView data for post-trade analysis

---

*This module contains the original production codebase.*
