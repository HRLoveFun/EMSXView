# EMSX Trading Tool — Project Structure

> Auto-generated project architecture reference. Last updated: 2026-02-26.

---

## 1. Overview

| Attribute | Value |
|-----------|-------|
| **Purpose** | Bloomberg EMSX order execution monitoring & management workstation |
| **Architecture** | Client-Server (React SPA ↔ FastAPI backend ↔ Bloomberg Terminal) |
| **Backend** | Python 3 / FastAPI / Bloomberg blpapi |
| **Frontend** | React 19 / TypeScript / Vite / Tailwind CSS / shadcn/ui |
| **Transport** | REST polling (1 s interval), WebSocket stub (future) |
| **Auth** | JWT (bypassed in local Bloomberg Terminal mode) |
| **Deployment** | Native Windows (PowerShell scripts) or Docker Compose |

---

## 2. Directory Layout

```
EMSX/                                   ← workspace root
│
├── docs/                               ← project documentation (this file)
│   ├── PROJECT_STRUCTURE.md
│   └── USER_GUIDE.md
│
├── app/                                ← frontend (React SPA)
│   ├── src/
│   │   ├── main.tsx                    ← React entry point
│   │   ├── App.tsx                     ← root component: auth, tabs, polling
│   │   ├── App.css                     ← app-specific styles
│   │   ├── index.css                   ← global Tailwind + dark theme vars
│   │   ├── types/index.ts             ← shared TypeScript interfaces
│   │   ├── services/api.ts            ← API client (fetch wrapper)
│   │   ├── lib/utils.ts               ← cn() Tailwind class merge
│   │   ├── hooks/use-mobile.ts        ← mobile breakpoint hook
│   │   ├── sections/                   ← page-level components
│   │   │   ├── MonitorBoard.tsx       ← risk/alert dashboard
│   │   │   ├── OrderTable.tsx         ← orders grid + inline filters
│   │   │   ├── RouteTable.tsx         ← routes/fills grid
│   │   │   ├── BatchOperationPanel.tsx← batch modify/cancel dialog
│   │   │   ├── Toolbar.tsx            ← top nav bar + connection status
│   │   │   └── ToastContainer.tsx     ← notification stack
│   │   └── components/ui/             ← shadcn/ui primitives (auto-generated)
│   ├── index.html                      ← HTML shell
│   ├── vite.config.ts                  ← Vite config (proxy, aliases)
│   ├── tailwind.config.js              ← Tailwind theme
│   ├── package.json                    ← npm dependencies
│   ├── .env                            ← runtime env (VITE_API_URL)
│   └── tsconfig*.json                  ← TypeScript configs
│
├── emsx-backend/                       ← backend service
│   ├── backend/
│   │   ├── main.py                     ← FastAPI app + Bloomberg service (~2050 lines)
│   │   ├── auth.py                     ← JWT auth module (demo users)
│   │   ├── requirements.txt            ← Python dependencies
│   │   ├── Dockerfile                  ← Docker build (optional)
│   │   └── logs/                       ← legacy log folder (redirected to root)
│   ├── config/                         ← infrastructure configs
│   │   ├── nginx.conf                  ← production Nginx (Docker)
│   │   ├── nginx-host.conf            ← host-network Nginx variant
│   │   ├── prometheus.yml              ← Prometheus scrape config
│   │   └── grafana/                    ← Grafana dashboard/datasource JSON
│   ├── scripts/
│   │   ├── deploy.sh                   ← Linux Docker deploy CLI
│   │   └── setup-windows.ps1          ← Windows Docker setup
│   ├── docker-compose.yml              ← production compose
│   ├── docker-compose.host.yml        ← host-network compose variant
│   ├── .env                            ← backend env variables
│   └── frontend/api-config.ts         ← (obsolete) old API client
│
├── logs/                               ← application logs (rotated, 3-day retention)
│
├── start-backend.ps1                   ← launch backend (native Python)
├── start-frontend.ps1                  ← launch frontend (Vite dev server)
├── launch-emsx.vbs                     ← one-click launcher (backend+frontend+browser)
├── create-desktop-shortcut.ps1        ← desktop shortcut creator
│
├── CLAUDE.md                           ← AI agent instructions
├── README.md                           ← master project documentation
├── EMSX API Developer's Guide.*       ← Bloomberg EMSX API reference (HTML/MD/PDF)
└── copilot_log.md                      ← development session log
```

---

## 3. Module Architecture

### 3.1 Backend (`emsx-backend/backend/main.py`)

The backend is a single-file FastAPI application structured in clearly separated sections:

| Section | Lines (approx) | Purpose |
|---------|----------------|---------|
| **Configuration** | 1–85 | `Settings` class, env vars, logging setup |
| **Data Models** | 86–350 | Pydantic models: `Order`, `Route`, `OrderFilters`, `BatchUpdateRequest`, `ApiResponse`, etc. |
| **Bloomberg Service** | 350–1590 | `BloombergEMSXService` class — connection, subscriptions, data processing, market data |
| **Auth & Helpers** | 1590–1650 | Token creation, verification (no-auth mode), audit logging |
| **FastAPI App** | 1650–1810 | Lifespan, CORS, app instance |
| **API Endpoints** | 1810–1980 | REST handlers: `/api/orders`, `/api/routes`, `/api/connection`, etc. |
| **WebSocket** | 1980–2020 | `ConnectionManager`, `/ws/orders` endpoint (stub) |
| **Error Handlers** | 2020–2050 | HTTP and general exception handlers |

#### `BloombergEMSXService` Internal Architecture

```
BloombergEMSXService
│
├── Connection Management
│   ├── connect()           → opens EMSX session + mktdata session
│   ├── disconnect()        → stops threads, closes sessions
│   └── get_status()        → returns ConnectionStatus
│
├── EMSX Subscription (Thread 1: emsx-subscription)
│   ├── _subscription_loop()         → subscribes to order + route topics
│   ├── _process_subscription_message() → updates _orders cache
│   ├── _process_route_message()     → updates _routes cache
│   ├── _parse_order_message()       → Bloomberg msg → Order model
│   └── _parse_route_message()       → Bloomberg msg → Route model
│
├── Market Data Subscription (Thread 2: mktdata-subscription)
│   ├── _mktdata_subscription_loop() → manages mktdata subscriptions + events
│   ├── _update_mktdata_subscriptions() → adds new / retries failed subs
│   ├── _process_mktdata_message()   → updates price/adv/vwap caches
│   └── _process_fx_message()        → updates FX rate cache
│
├── Request/Response Helpers
│   ├── _send_request()    → synchronous EMSX request with timeout
│   ├── modify_order()     → ModifyOrderEx
│   ├── cancel_order()     → CancelOrderEx
│   └── batch_update()     → iterate modify/cancel
│
├── Public API (called by endpoints)
│   ├── get_orders()       → returns enriched order list with filters
│   └── get_routes()       → returns routes enriched with parent order data
│
└── Utilities
    ├── _msg_safe_int/float/str()  → safe Bloomberg message field extraction
    ├── _derive_currency()         → currency from ticker/exchange suffix
    └── _EXCHANGE_CURRENCY_MAP     → exchange code → currency mapping
```

#### Data Flow

```
Bloomberg Terminal (port 8194)
    │
    ├── //blp/emapisvc/order  ──→  _subscription_loop  ──→  _orders dict
    ├── //blp/emapisvc/route  ──→  _subscription_loop  ──→  _routes dict
    └── //blp/mktdata         ──→  _mktdata_subscription_loop
            ├── CHG_PCT_1D, VOLUME_AVG_5D, VWAP  ──→  _price_changes, _adv5d, _mkt_vwap
            └── FX LAST_PRICE                     ──→  _fx_rates
                │
                └──→  get_orders() merges all caches → enriched Order list → JSON API
```

### 3.2 Frontend (`app/src/`)

#### Component Hierarchy

```
main.tsx
└── App.tsx
    ├── LoginScreen (inline, bypassed)
    ├── Toolbar               ← top bar: refresh, connection status, logout
    ├── Tab: Monitor
    │   └── MonitorBoard      ← risk flags, grouped alerts
    ├── Tab: Orders
    │   ├── OrderTable        ← full order grid + inline filters + sorting + grouping
    │   └── BatchOperationPanel ← batch modify/cancel
    └── Tab: Routes
        └── RouteTable        ← route-level fill data
    ToastContainer            ← notification overlay
```

#### Data Flow

```
App.tsx
  │
  ├── useEffect (poll every 1s)
  │   ├── apiService.getOrders()  → setAllOrders
  │   └── apiService.getRoutes()  → setAllRoutes
  │
  ├── useMemo (filteredOrders)    ← client-side filtering (instant)
  │
  └── Props cascade:
      ├── MonitorBoard  ← allOrders
      ├── OrderTable    ← filteredOrders, allOrders, selectedOrders, filters
      ├── RouteTable    ← allRoutes
      └── Toolbar       ← orderCount (filtered or flagged count by active tab)
```

### 3.3 Auth (`emsx-backend/backend/auth.py`)

| Component | Purpose |
|-----------|---------|
| `AuthManager` | Demo user store, password hashing, JWT creation/verification |
| `get_current_user()` | FastAPI dependency for protected endpoints |
| `verify_token()` (in main.py) | **No-auth passthrough** — all requests trusted from localhost |

> In production: replace `verify_token()` no-op with `get_current_user()` from auth.py.

---

## 4. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info + Bloomberg status |
| GET | `/api/health` | Health check |
| POST | `/api/auth/login` | JWT login (demo users) |
| GET | `/api/connection` | Bloomberg connection status |
| POST | `/api/connection/reconnect` | Force Bloomberg reconnection |
| GET | `/api/orders` | List orders (with optional query filters) |
| GET | `/api/orders/refresh` | Force-refresh order cache |
| POST | `/api/orders/batch-update` | Batch modify/cancel orders |
| POST | `/api/orders/{id}/cancel` | Cancel single order |
| GET | `/api/routes` | List routes |
| WS | `/ws/orders` | WebSocket (stub — ping/pong only) |

---

## 5. Key Data Models

### Order (backend ↔ frontend)

Core EMSX fields: `id` (EMSX_SEQUENCE), `symbol`, `side`, `status`, `orderType`, `quantity`, `filledQuantity`, `price`, `avgPrice`, `timeInForce`, `account`, `portfolio`, `trader`, `currency`, `exchange`

Enriched fields (from `//blp/mktdata`): `pctChange` (CHG_PCT_1D), `adv5d` (VOLUME_AVG_5D), `mktVwap` (VWAP), `dollarValueUsd` (dollarValue × FX rate)

Custom fields: `customNote1`–`customNote5`, `traderNotes`, `execInstruction`, `strategyType`, `strategyPartRate`, `broker`, `dayAvgPrice`

### Route (backend ↔ frontend)

Core: `routeId`, `sequence`, `status`, `broker`, `amount`, `filled`, `working`, `avgPrice`, `limitPrice`, execution strategy fields, settlement/commission fields

Enriched from parent order: `ticker`, `side`, `portfolio`, `trader`, `currency`

---

## 6. Bloomberg Sessions

| Session | Service | Thread | Purpose |
|---------|---------|--------|---------|
| Main (`self.session`) | `//blp/emapisvc` | `emsx-subscription` | EMSX order + route subscriptions; ModifyOrderEx / CancelOrderEx requests |
| Market Data (`self._mktdata_session`) | `//blp/mktdata` | `mktdata-subscription` | Streaming market data (price change, ADV, VWAP) + FX rates |

Both sessions connect to `localhost:8194` (Bloomberg Terminal API).

---

## 7. Configuration

### Backend Environment (`emsx-backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BLOOMBERG_HOST` | `localhost` | Bloomberg API host |
| `BLOOMBERG_PORT` | `8194` | Bloomberg API port |
| `API_HOST` | `0.0.0.0` | Backend listen address |
| `API_PORT` | `3000` | Backend listen port |
| `JWT_SECRET` | (set in .env) | JWT signing key |
| `JWT_EXPIRE_MINUTES` | `480` | Token TTL (8 hours) |
| `ALLOWED_ORIGINS` | `localhost:5173,localhost:80` | CORS origins |

### Frontend Environment (`app/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | (empty) | API base URL. Empty = Vite proxy to :3000 |
| `VITE_USE_MOCK` | `false` | Mock mode (not implemented) |

---

## 8. Technology Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language (BE) | Python | 3.x (Anaconda) |
| Framework (BE) | FastAPI | 0.109.0 |
| ASGI Server | Uvicorn | 0.27.0 |
| Bloomberg API | blpapi | 3.23.0 |
| Auth | python-jose, passlib | 3.3.0, 1.7.4 |
| Language (FE) | TypeScript | ~5.9 |
| Framework (FE) | React | 19 |
| Build (FE) | Vite | 7 |
| CSS | Tailwind CSS | 3 |
| UI Components | shadcn/ui (Radix) | latest |
| Charts | Recharts | (installed, unused) |
| Icons | Lucide React | latest |
