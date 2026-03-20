# EMSX Project Structure

> Comprehensive architecture documentation for the EMSX Trading Platform
> Last updated: 2026-03-20 | Version: 2.0

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Hierarchical Tree View](#hierarchical-tree-view)
3. [Detailed File Breakdown](#detailed-file-breakdown)
   - [Frontend (app/)](#frontend-app)
   - [Backend (emsx-backend/)](#backend-emsx-backend)
   - [Scripts (scripts/)](#scripts-scripts)
   - [Documentation (docs/)](#documentation-docs)
   - [Data & Configuration](#data--configuration)
4. [Risk & Defect Analysis](#risk--defect-analysis)

---

## Project Overview

The **EMSX Trading Platform** is a Bloomberg EMSX (Execution Management System) order and route management tool with the following architecture:

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui | Trading dashboard UI |
| **Backend** | Python 3.11 + FastAPI + blpapi | Bloomberg EMSX API integration |
| **Infrastructure** | Docker Compose + Nginx + Redis | Deployment & caching |
| **Data Source** | Bloomberg Terminal EMSX API | Live order/route data |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              BROWSER                                     │
│                     http://localhost:5173 (dev)                         │
│                     http://localhost (prod Docker)                      │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
┌───────────────────────────────▼─────────────────────────────────────────┐
│                           FRONTEND (React)                               │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────────────┐  │
│  │ Monitor Tab │  │ Execution Tab │  │         Settings Tab           │  │
│  │  (Alerts)   │  │ Orders/Routes │  │  Broker Algorithms & Config    │  │
│  └─────────────┘  └──────────────┘  └─────────────────────────────────┘  │
│                                                                          │
│  Vite 7 + TypeScript 5.9 + Tailwind 3.4 + shadcn/ui + Radix UI           │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ HTTP/REST + WebSocket
┌───────────────────────────────▼─────────────────────────────────────────┐
│                           BACKEND (FastAPI)                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    EmsxSessionManager Class                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │   │
│  │  │self.session  │  │_request_sess │  │    _mktdata_session     │ │   │
│  │  │(Subscriptions)│  │(Request/Resp)│  │   (Market Data)         │ │   │
│  │  └──────────────┘  └──────────────┘  └─────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  Python 3.11 + FastAPI + blpapi 3.23 + JWT Auth + Pydantic v2            │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ blpapi (Bloomberg API)
┌───────────────────────────────▼─────────────────────────────────────────┐
│                        BLOOMBERG TERMINAL                                │
│                     localhost:8194 (EMSX API)                           │
│              Services: //blp/emapisvc, //blp/emapisvc_beta              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Hierarchical Tree View

```
EMSX/
├── README.md                          # Project overview and deployment guide
├── CLAUDE.md                          # Development guidelines and verification checklist
├── HANDOFF.md                         # Session continuity log with blockers/decisions
├── MEMORY.md                          # Architectural decisions and API contracts
├── PROJECT_STRUCTURE.md               # This file - comprehensive architecture doc
├── .gitignore                         # Git ignore rules
│
├── app/                               # Frontend React Application
│   ├── index.html                     # HTML entry point
│   ├── package.json                   # NPM dependencies (React 19, Vite 7, etc.)
│   ├── tsconfig.json                  # TypeScript configuration
│   ├── tsconfig.app.json              # TypeScript app-specific config
│   ├── tsconfig.node.json             # TypeScript node-specific config
│   ├── vite.config.ts                 # Vite build configuration with API proxy
│   ├── tailwind.config.js             # Tailwind CSS theme configuration
│   ├── postcss.config.js              # PostCSS configuration
│   ├── eslint.config.js               # ESLint configuration
│   ├── components.json                # shadcn/ui configuration
│   ├── Dockerfile                     # Multi-stage Docker build
│   │
│   ├── src/
│   │   ├── main.tsx                   # React app entry point (StrictMode)
│   │   ├── App.tsx                    # Main app component with tab routing
│   │   ├── index.css                  # Global CSS styles
│   │   ├── App.css                    # App-specific CSS
│   │   │
│   │   ├── components/                # React components
│   │   │   ├── ui/                    # 50+ shadcn/ui base components
│   │   │   │   ├── button.tsx
│   │   │   │   ├── table.tsx
│   │   │   │   ├── dialog.tsx
│   │   │   │   ├── select.tsx
│   │   │   │   ├── tabs.tsx
│   │   │   │   └── ... (50 total)
│   │   │   ├── order-modify-dialog.tsx      # Order modification dialog
│   │   │   ├── order-route-dialog.tsx       # Route creation dialog
│   │   │   ├── route-action-menu.tsx        # Route row action dropdown
│   │   │   ├── route-modify-dialogs.tsx     # Route modification dialogs
│   │   │   └── strategy-data-manager.tsx    # Import/export strategy config
│   │   │
│   │   ├── sections/                  # Page section components
│   │   │   ├── Toolbar.tsx            # Header with refresh, connection status
│   │   │   ├── MonitorBoard.tsx       # Alert conditions + flagged orders
│   │   │   ├── LazyOrderBoard.tsx     # Non-active orders view
│   │   │   ├── ExecutionBoard.tsx     # Orders/Routes tab container
│   │   │   ├── OrderTable.tsx         # Orders table with filters/grouping
│   │   │   ├── RouteTable.tsx         # Routes table with actions
│   │   │   ├── BatchOperationPanel.tsx # Batch modify selected orders
│   │   │   ├── SettingsBoard.tsx      # Settings: algorithms + frequencies
│   │   │   └── ToastContainer.tsx     # Toast notifications
│   │   │
│   │   ├── hooks/                     # Custom React hooks
│   │   │   ├── use-mobile.ts          # Mobile detection hook
│   │   │   └── use-broker-algorithms.ts # Broker algorithms data hook
│   │   │
│   │   ├── lib/                       # Utility libraries
│   │   │   ├── utils.ts               # General utilities (cn function)
│   │   │   ├── format-utils.ts        # Number/date formatting
│   │   │   ├── cache-manager.ts       # Caching utilities
│   │   │   ├── monitor-conditions.ts  # Alert condition logic
│   │   │   └── table-constants.ts     # Grouping/filtering options
│   │   │
│   │   ├── services/                  # API services
│   │   │   ├── api.ts                 # Main API client service
│   │   │   └── strategy-data-service.ts # Strategy file management
│   │   │
│   │   └── types/                     # TypeScript type definitions
│   │       └── index.ts               # All type exports (260 lines)
│   │
│   ├── public/                        # Static assets
│   │   └── strategy-data/             # Strategy JSON files
│   │       ├── default-strategies.json
│   │       ├── default-strategy-params.json
│   │       ├── EXPORT_EXAMPLE.json
│   │       └── README.md
│   │
│   └── dist/                          # Build output (generated)
│
├── emsx-backend/                      # Python FastAPI Backend
│   ├── docker-compose.yml             # Docker Compose production config
│   ├── docker-compose.host.yml        # Linux host-network variant
│   │
│   ├── backend/
│   │   ├── main.py                    # FastAPI main app (3695 lines)
│   │   ├── auth.py                    # JWT authentication module
│   │   ├── start_server.py            # Server startup script
│   │   ├── requirements.txt           # Python dependencies
│   │   └── Dockerfile                 # Python multi-stage build
│   │
│   ├── config/                        # Infrastructure configuration
│   │   ├── nginx.conf                 # Nginx reverse proxy config
│   │   ├── nginx-host.conf            # Linux host-network variant
│   │   ├── prometheus.yml             # Prometheus scraping config
│   │   └── grafana/                   # Grafana dashboards/datasources
│   │
│   └── scripts/                       # Deployment scripts
│       ├── deploy.sh                  # Linux/macOS deployment
│       └── setup-windows.ps1          # Windows deployment
│
├── scripts/                           # Utility scripts
│   ├── cleanup-logs.ps1               # Log cleanup and maintenance
│   ├── export-localstorage-cache.js   # Cache export utility
│   │
│   ├── deploy/                        # Deployment scripts
│   │   ├── start-backend.ps1          # Start backend (no Docker)
│   │   ├── start-frontend.ps1         # Start frontend (no Docker)
│   │   ├── launch-emsx.vbs            # One-click launcher (VBScript)
│   │   ├── create-desktop-shortcut.ps1 # Create desktop shortcut
│   │   └── logs/                      # Deployment logs
│   │
│   └── diagnose/                      # Diagnostic scripts
│       ├── diagnose_order.py          # Order calculation diagnostics
│       ├── diagnose_market_data.py    # Market data enrichment diagnostics
│       ├── diagnose_odd_lot.py        # Odd lot detection diagnostics
│       └── test_hash.py               # Hash function test
│
├── docs/                              # Documentation
│   ├── FRONTEND_UI_DESCRIPTION.md     # UI specification (source of truth)
│   ├── ERROR_PATTERNS.md              # Error patterns knowledge base
│   ├── KNOWLEDGE_WORKFLOW.md          # Knowledge management workflow
│   ├── SESSION_DIGEST.md              # Weekly session summaries
│   ├── USER_GUIDE.md                  # End user guide
│   ├── strategy-file-storage.md       # Strategy storage documentation
│   │
│   ├── reference/                     # External references
│   │   ├── EMSX-API-Complete-Guide.md # Full EMSX API guide
│   │   └── EMSX-API-Quick-Reference.md # Quick reference
│   │
│   ├── features/                      # Feature documentation
│   │   └── route-modify/
│   │       ├── spec.md                # Route modify specification
│   │       └── implementation.md      # Implementation details
│   │
│   └── session_captures/              # Session capture archive
│       ├── README.md
│       ├── 2026-03-16/
│       └── archived/
│
├── data/                              # Reference data
│   ├── emsx_field_metadata.csv        # EMSX field metadata export
│   └── get_all_field_metadata.py      # Bloomberg field fetcher
│
├── archive/                           # Archived/completed docs
│   ├── Broker_Access.xlsx
│   ├── EMSX API Developer's Guide_raw.md
│   ├── FIELD_ANALYSIS.md
│   ├── OPTIMIZATION_SUMMARY.md
│   └── PROJECT_ANALYSIS.md
│
└── logs/                              # Runtime logs (gitignored)
    └── emsx_api.log                   # Backend API logs
```

---

## Detailed File Breakdown

### Frontend (`app/`)

#### Entry Points & Configuration

| File | Lines | Purpose | Dependencies |
|------|-------|---------|--------------|
| `src/main.tsx` | 11 | React application entry point | `react`, `react-dom`, `./App.tsx` |
| `src/App.tsx` | 524 | Main app component with tab routing, state management | All sections, services, hooks |
| `index.html` | 13 | HTML entry point | Vite build |
| `vite.config.ts` | 48 | Vite configuration with API proxy | `vite`, `@vitejs/plugin-react` |
| `package.json` | 79 | NPM dependencies | React 19, Vite 7, Tailwind 3.4, etc. |
| `tsconfig.json` | 17 | TypeScript configuration | - |
| `tailwind.config.js` | 84 | Tailwind CSS theme config | Custom trading colors |

#### Type Definitions (`src/types/index.ts`)

**Core Types & Interfaces:**

| Type/Interface | Purpose | Key Fields |
|---------------|---------|------------|
| `OrderSide` | Enum for order direction | `'BUY' \| 'SELL'` |
| `OrderStatus` | Enum for order states | `NEW, WORKING, PARTIAL, FILLED, CANCELLED, ...` |
| `OrderType` | Enum for order types | `LIMIT, MARKET, STOP, STOP_LIMIT` |
| `TimeInForce` | Enum for TIF options | `DAY, GTC, IOC, FOK` |
| `Order` | Order entity | `id, symbol, side, status, quantity, filledQuantity, ...` |
| `Route` | Route entity | `id, routeId, sequence, status, broker, amount, ...` |
| `OrderFilters` | Filter criteria | `symbol?, side?, status?, orderType?, ...` |
| `BatchUpdateRequest` | Batch update payload | `orderIds, field, value` |
| `Toast` | Notification type | `id, type, message, duration?` |
| `TraderInfo` | Trader information | `traderName` |
| `BrokerAlgorithmConfig` | Broker config | `broker, exchange, strategies` |
| `StrategyConfig` | Strategy definition | `name, parameters` |
| `StrategyParameter` | Strategy param | `fieldName, stringValue, disable, dataType, description` |

#### Services (`src/services/`)

**`api.ts` (432 lines)**

| Export | Type | Purpose | Methods |
|--------|------|---------|---------|
| `tokenService` | Object | JWT token management | `getToken()`, `setToken()`, `removeToken()`, `isAuthenticated()` |
| `apiService` | Object | Base API client | `getOrders()`, `getRoutes()`, `batchUpdate()`, `checkConnection()`, `cancelRoute()`, `modifyRoute()`, `modifyOrder()`, `routeOrder()`, `getBrokers()`, `getBrokerStrategies()`, `getBrokerStrategyInfo()` |
| `cachedApiService` | Object | Cached API wrapper | Same methods with caching layer |

**`strategy-data-service.ts` (346 lines)**

| Function | Inputs | Outputs | Purpose |
|----------|--------|---------|---------|
| `loadStrategyFiles()` | - | `Promise<StrategyFiles>` | Load strategy JSON files |
| `getBrokerStrategiesFromFile(broker, assetClass?)` | `string, string?` | `string[]` | Get strategies from file cache |
| `getStrategyInfoFromFile(broker, strategy, assetClass?)` | `string, string, string?` | `StrategyParameter[]` | Get strategy params from file |
| `exportConfiguration()` | - | `void` | Export current config to JSON file |
| `importConfiguration(file)` | `File` | `Promise<boolean>` | Import config from JSON file |
| `mergeWithDefaults(apiFields, fileFields)` | `StrategyParameter[], StrategyParameter[]` | `StrategyParameter[]` | Merge API and file data |

#### Utility Libraries (`src/lib/`)

**`utils.ts` (7 lines)**

| Function | Inputs | Outputs | Purpose |
|----------|--------|---------|---------|
| `cn(...inputs)` | `ClassValue[]` | `string` | Merge Tailwind classes with `clsx` + `tailwind-merge` |

**`format-utils.ts` (52 lines)**

| Function | Inputs | Outputs | Purpose |
|----------|--------|---------|---------|
| `fmtNum(v, decimals=2)` | `number \| null, number?` | `string` | Format number with decimals |
| `fmtInt(v)` | `number \| null` | `string` | Format integer |
| `fmtPct(v)` | `number \| null` | `string` | Format percentage |
| `fmtDollar(v)` | `number \| null` | `string` | Format dollar value (K/M notation) |
| `formatInt(v)` | `number \| null` | `string` | Format integer (non-zero only) |
| `getSideClass(side)` | `string` | `string` | Get CSS class for Buy/Sell |

**`cache-manager.ts` (340 lines)**

| Export | Type | Purpose |
|--------|------|---------|
| `CacheManager<T>` | Class | Generic cache manager with TTL |
| `CACHE_CONFIGS` | Object | Predefined cache configurations |
| `createCache<T>(config)` | Function | Create cache instance |
| `getOrFetch<T>()` | Function | Get or fetch data with caching |
| `clearAllCaches()` | Function | Clear all caches |
| `getCacheStats()` | Function | Get cache statistics |

**Cache Configurations:**

| Config | TTL | Storage | Purpose |
|--------|-----|---------|---------|
| `ORDERS` | 2s | Memory | Order data (high frequency) |
| `ROUTES` | 2s | Memory | Route data (high frequency) |
| `CONNECTION_STATUS` | 30s | Memory | Connection status |
| `TRADER_INFO` | 7 days | LocalStorage | Trader information |
| `BROKER_STRATEGIES` | 24h | LocalStorage | Broker strategies |
| `STRATEGY_INFO` | 24h | LocalStorage | Strategy parameters |

**`monitor-conditions.ts` (205 lines)**

| Export | Type | Purpose |
|--------|------|---------|
| `DEFAULT_CONDITIONS` | Object | Default monitor conditions |
| `CONDITION_DEFS` | Array | Condition definitions array |
| `loadConditions()` | Function | Load from LocalStorage |
| `saveConditions(c)` | Function | Save to LocalStorage |
| `matchesAnyCondition(order, conditions)` | Function | Check order against conditions |
| `getOrderFlags(order, conditions)` | Function | Get flag badges for order |

**Condition Types:**
- `dollarValueLow` - Dollar value below threshold
- `dollarValueHigh` - Dollar value above threshold  
- `pctChangeBuy` - Buy orders with % change above threshold
- `pctChangeSell` - Sell orders with % change below threshold
- `qtyAdvRatio` - Quantity/ADV ratio above threshold
- `oddLot` - Odd lot orders (Japan market)

**`table-constants.ts` (77 lines)**

| Export | Value |
|--------|-------|
| `ORDER_GROUP_BY_OPTIONS` | 8 grouping options (Exchange, Ticker, Side, etc.) |
| `ROUTE_GROUP_BY_OPTIONS` | 8 grouping options |
| `STATUS_OPTIONS` | 11 order status options |
| `ORDER_TYPE_OPTIONS` | 4 order type options |
| `ROUTE_STATUS_OPTIONS` | 8 route status options |

#### Custom Hooks (`src/hooks/`)

**`use-mobile.ts` (20 lines)**

| Hook | Returns | Purpose |
|------|---------|---------|
| `useIsMobile()` | `boolean` | Detect mobile device via user agent |

**`use-broker-algorithms.ts` (728 lines)**

| Hook | Returns | Purpose |
|------|---------|---------|
| `useBrokerAlgorithms()` | Object with state and methods | Manage broker algorithm configuration |

**Return Properties:**

| Property | Type | Description |
|----------|------|-------------|
| `configs` | `BrokerAlgorithmConfig[]` | Configuration list |
| `isLoading` | `boolean` | Loading state |
| `isRefreshing` | `boolean` | Refresh state |
| `lastUpdated` | `Date \| null` | Last update timestamp |
| `error` | `string \| null` | Error message |
| `refreshData()` | `() => Promise<void>` | Refresh from backend |
| `getStrategiesForBroker(broker)` | `(string) => StrategyConfig[]` | Get strategies |
| `getParametersForStrategy(broker, strategy)` | `(string, string) => StrategyParameter[]` | Get parameters |
| `getExchanges()` | `() => string[]` | Get exchanges |
| `getBrokersForExchange(exchange)` | `(string) => string[]` | Get brokers for exchange |

#### Section Components (`src/sections/`)

**`Toolbar.tsx` (164 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `onRefresh` | `() => void` | Refresh callback |
| `onClearCache?` | `() => void` | Clear cache callback |
| `isLoading` | `boolean` | Loading state |
| `orderCount` | `number` | Order count display |
| `onLogout` | `() => void` | Logout callback |

**`MonitorBoard.tsx` (528 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `allOrders` | `Order[]` | All orders data |
| `isLoading` | `boolean` | Loading state |
| `conditions` | `MonitorConditions` | Alert conditions |
| `onConditionsChange` | `(c: MonitorConditions) => void` | Condition change callback |

**Functions:**
- `filterOrders()` - Filter orders matching conditions
- `groupOrders()` - Group orders by selected criteria
- `renderConditionPanel()` - Render condition configuration UI
- `renderOrderTable()` - Render flagged orders table

**`LazyOrderBoard.tsx` (145 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `allOrders` | `Order[]` | All orders |
| `isLoading` | `boolean` | Loading state |

**Filtering:** Excludes `WORKING`, `QUEUED`, `COMPLETED`, `FILLED`, `SUSPENDED`

**`ExecutionBoard.tsx` (112 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `orders` | `Order[]` | Filtered orders |
| `allOrders` | `Order[]` | All orders |
| `routes` | `Route[]` | Routes |
| `selectedOrders` | `Set<string>` | Selected order IDs |
| `onSelectionChange` | `(ids: Set<string>) => void` | Selection change |
| `isLoading` | `boolean` | Loading state |
| `filters` | `OrderFilters` | Active filters |
| `onFilterChange` | `(filters: OrderFilters) => void` | Filter change |
| `currentTrader` | `string` | Current trader name |
| `onBatchUpdate` | `(request: BatchUpdateRequest) => Promise<void>` | Batch update |
| `onClearSelection` | `() => void` | Clear selection |
| `onCancelRoute?` | `(request: CancelRouteRequest) => Promise<void>` | Cancel route |
| `onModifyRoute?` | `(request: ModifyRouteRequest) => Promise<void>` | Modify route |
| `onModifyOrder?` | `(request: ModifyOrderRequest) => Promise<void>` | Modify order |
| `onRouteOrder?` | `(request: RouteOrderRequest) => Promise<void>` | Route order |
| `onRefresh?` | `() => Promise<void>` | Refresh callback |

**`OrderTable.tsx` (659 lines)**

**Features:**
- Multi-selection with checkboxes
- Grouping by 8 criteria
- Column sorting
- Filter popovers per column
- Modify order dialog
- Route order dialog

**`RouteTable.tsx` (788 lines)**

**Features:**
- Two-level grouping (primary + secondary)
- Status/Broker/Trader filters (include/exclude mode)
- Ticker text filter
- Route action menu (Cancel, Modify Amount, Modify Type, Modify Limit Price, Broker/Strategy)

**`BatchOperationPanel.tsx` (296 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `selectedCount` | `number` | Number of selected orders |
| `onBatchUpdate` | `(request: BatchUpdateRequest) => Promise<void>` | Batch update handler |
| `onClearSelection` | `() => void` | Clear selection handler |
| `isLoading` | `boolean` | Loading state |

**Supported Batch Fields:** `price`, `quantity`, `timeInForce`, `status`

**`SettingsBoard.tsx` (849 lines)**

**Features:**
- Global settings toggles (monitor alerts, desktop notifications)
- Broker algorithm tree (3-level hierarchy)
- Parameter update frequency table
- Strategy Data Manager integration

**`ToastContainer.tsx` (73 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `toasts` | `Toast[]` | Toast messages array |
| `onRemove` | `(id: string) => void` | Remove callback |

#### Dialog Components (`src/components/`)

**`order-modify-dialog.tsx` (289 lines)**

| Export | Type | Description |
|--------|------|-------------|
| `OrderModifyDialog` | Component | Order modification dialog |
| `OrderUpdates` | Interface | Updatable fields interface |

**`order-route-dialog.tsx` (449 lines)**

| Export | Type | Description |
|--------|------|-------------|
| `RouteOrderDialog` | Component | Route creation dialog |
| `RouteOrderData` | Interface | Route data interface |

**Fields:** Broker, Route Quantity, Order Type, Limit Price, Stop Price, TIF, Exchange Destination, Route Notes

**`route-action-menu.tsx` (130 lines)**

| Prop | Type | Description |
|------|------|-------------|
| `route` | `Route` | Route object |
| `currentTrader` | `string` | Current trader |
| `onCancel` | `(route: Route) => void` | Cancel callback |
| `onModifyAmount` | `(route: Route) => void` | Modify amount callback |
| `onModifyType` | `(route: Route) => void` | Modify type callback |
| `onModifyLimitPrice` | `(route: Route) => void` | Modify price callback |
| `onBrokerStrategy` | `(route: Route) => void` | Broker/strategy callback |

**`route-modify-dialogs.tsx` (995 lines)**

**Exports:**
- `CancelRouteDialog` - Confirmation dialog
- `ModifyAmountDialog` - Amount modification
- `ModifyOrderTypeDialog` - Order type modification
- `ModifyLimitPriceDialog` - Limit price modification
- `BrokerStrategyDialog` - Broker/strategy modification

**`strategy-data-manager.tsx` (287 lines)**

**Features:**
- View cache status
- Clear cache
- Reload files
- Export configuration
- Import configuration

#### UI Components (`src/components/ui/`)

50+ shadcn/ui base components including:

| Component | Purpose |
|-----------|---------|
| `button.tsx` | Button variants |
| `table.tsx` | Table with headers, rows, cells |
| `dialog.tsx` | Modal dialogs |
| `select.tsx` | Dropdown selects |
| `tabs.tsx` | Tab navigation |
| `checkbox.tsx` | Checkboxes |
| `input.tsx` | Text inputs |
| `badge.tsx` | Status badges |
| `tooltip.tsx` | Tooltips |
| `dropdown-menu.tsx` | Dropdown menus |
| `popover.tsx` | Popover containers |
| `scroll-area.tsx` | Scrollable areas |
| `separator.tsx` | Visual separators |
| `sonner.tsx` | Toast notifications |
| `sidebar.tsx` | Sidebar navigation |

---

### Backend (`emsx-backend/`)

#### Main Application (`backend/main.py`) - 3695 lines

**Core Classes:**

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `Settings` | Pydantic settings | Environment variable validation |
| `EmsxSessionManager` | Bloomberg session management | `connect()`, `disconnect()`, `get_orders()`, `get_routes()`, `create_route()`, `cancel_route()`, `modify_route()` |
| `MarketDataManager` | Market data subscriptions | `subscribe()`, `unsubscribe()`, `get_price_changes()` |
| Various `*Request`/`Response` | Pydantic models | API request/response schemas |

**Key Enums:**

| Enum | Values |
|------|--------|
| `OrderSide` | `BUY`, `SELL` |
| `OrderStatus` | `NEW`, `ASSIGN`, `WORKING`, `PARTIAL`, `FILLED`, `CANCELLED`, `COMPLETED`, `QUEUED`, `SUSPENDED`, `PENDING_CANCEL`, `REJECTED`, `SENT`, `A_SENT`, `ROUTED`, `ACTIVE`, `PENDING`, `PEND_NEW` |
| `OrderType` | `LIMIT`, `MARKET`, `STOP`, `STOP_LIMIT` |
| `TimeInForce` | `DAY`, `GTC`, `IOC`, `FOK` |

**API Endpoints:**

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| GET | `/api/health` | Health check | No |
| GET | `/api/docs` | Swagger UI | No |
| POST | `/api/auth/login` | JWT login | No |
| GET | `/api/orders` | Get orders | Yes |
| POST | `/api/orders/batch-update` | Batch update | Yes |
| POST | `/api/orders/modify` | Modify order | Yes |
| POST | `/api/orders/route` | Create route | Yes |
| GET | `/api/routes` | Get routes | Yes |
| POST | `/api/routes/cancel` | Cancel route | Yes |
| POST | `/api/routes/modify` | Modify route | Yes |
| GET | `/api/brokers` | Get brokers | Yes |
| GET | `/api/broker-strategies` | Get strategies | Yes |
| GET | `/api/broker-strategy-info` | Get strategy info | Yes |
| GET | `/api/connection` | Check connection | Yes |
| POST | `/api/connection/reconnect` | Reconnect | Yes |
| GET | `/api/trader-info` | Get trader info | Yes |
| WS | `/ws/orders` | Real-time orders | No |

**Session Architecture (3 Sessions):**

| Session | Purpose | Bloomberg Operations |
|---------|---------|---------------------|
| `self.session` | Order/Route subscriptions | `CreateOrderEx`, `RouteEx` events |
| `self._request_session` | Request/Response operations | `GetOrdersEx`, `GetRoutesEx`, `ModifyRouteEx` |
| `self._mktdata_session` | Market data subscriptions | Price changes, ADV data |

#### Authentication (`backend/auth.py`) - 174 lines

| Export | Type | Purpose |
|--------|------|---------|
| `AuthManager` | Class | JWT authentication management |
| `get_current_user` | Dependency | FastAPI dependency for protected routes |
| `audit_log` | Function | Audit logging decorator |

**AuthManager Methods:**

| Method | Inputs | Outputs | Purpose |
|--------|--------|---------|---------|
| `verify_password(plain, hashed)` | `string, string` | `boolean` | Verify password |
| `get_password_hash(password)` | `string` | `string` | Hash password |
| `authenticate_user(username, password)` | `string, string` | `User \| None` | Authenticate user |
| `create_access_token(user, expires_delta?)` | `User, timedelta?` | `string` | Create JWT token |
| `verify_token(token)` | `string` | `TokenData` | Verify JWT token |

#### Dependencies (`backend/requirements.txt`)

| Category | Dependencies |
|----------|--------------|
| Web Framework | `fastapi==0.109.0`, `uvicorn[standard]==0.27.0` |
| Bloomberg API | `blpapi==3.23.0` |
| Authentication | `python-jose[cryptography]==3.3.0`, `passlib[bcrypt]==1.7.4` |
| Data Validation | `pydantic==2.5.3`, `pydantic-settings==2.1.0` |
| Async Support | `asyncio-mqtt==0.16.1`, `websockets==12.0` |
| Monitoring | `structlog==24.1.0`, `prometheus-client==0.19.0` |
| Utilities | `python-dateutil`, `pytz`, `orjson`, `python-dotenv` |

---

### Scripts (`scripts/`)

#### Deployment Scripts (`scripts/deploy/`)

**`start-backend.ps1` (41 lines)**

| Function | Description |
|----------|-------------|
| Load `.env` config | Parses env file and sets environment variables |
| Start uvicorn | Launches FastAPI on port 3000 |
| Log directory setup | Ensures `logs/` directory exists |

**`start-frontend.ps1` (11 lines)**

| Function | Description |
|----------|-------------|
| Change directory | To `app/` |
| Start Vite dev server | `npm run dev` on port 5173 |

**`launch-emsx.vbs` (29 lines)**

| Function | Description |
|----------|-------------|
| Launch backend | Hidden PowerShell window |
| Wait | 6 seconds for backend ready |
| Launch frontend | Hidden PowerShell window |
| Wait | 7 seconds for Vite compile |
| Open browser | `http://localhost:5173` |

**`create-desktop-shortcut.ps1` (30 lines)**

| Function | Description |
|----------|-------------|
| Create shortcut | On desktop |
| Icon selection | Bloomberg terminal icon if available |
| Target | `wscript.exe` with VBS argument |

#### Diagnostic Scripts (`scripts/diagnose/`)

**`diagnose_order.py` (124 lines)**

| Function | Description |
|----------|-------------|
| `main()` | Simulates order 4880806 calculation logic |

**Purpose:** Debug `dollarValueUsd` calculation for specific order

**`diagnose_market_data.py` (121 lines)**

| Function | Description |
|----------|-------------|
| `main()` | Analyzes market data enrichment issues |

**Purpose:** Debug why `%Change` and `ADV 5D` may be empty

**`diagnose_odd_lot.py` (112 lines)**

| Function | Description |
|----------|-------------|
| `test_api()` | Tests API for odd lot detection |

**Purpose:** Verify odd lot calculation for US/JP markets

#### Maintenance Scripts

**`cleanup-logs.ps1` (112 lines)**

| Function | Description |
|----------|-------------|
| `main()` | Log cleanup and maintenance |

**Parameters:**
- `-Force` - Actually delete (default dry-run)
- `-MaxAgeDays` - Default 3 days
- `-MaxFiles` - Default 3 files
- `-LogDir` - Default `logs/` directory

---

### Documentation (`docs/`)

| File | Lines | Purpose |
|------|-------|---------|
| `FRONTEND_UI_DESCRIPTION.md` | 453 | UI specification (source of truth) |
| `ERROR_PATTERNS.md` | 400+ | Error patterns knowledge base |
| `KNOWLEDGE_WORKFLOW.md` | 300+ | Knowledge management workflow |
| `SESSION_DIGEST.md` | 250+ | Weekly session summaries |
| `USER_GUIDE.md` | 300+ | End user documentation |
| `strategy-file-storage.md` | 100+ | Strategy storage documentation |
| `reference/EMSX-API-Complete-Guide.md` | 3900+ | Full EMSX API documentation |
| `reference/EMSX-API-Quick-Reference.md` | 600+ | Quick reference guide |

---

### Data & Configuration

**`data/emsx_field_metadata.csv`**

Bloomberg EMSX field metadata with columns:
- `EMSX_FIELD_NAME` - API field name
- `EMSX_DISP_NAME` - Display name
- `EMSX_TYPE` - Data type
- `EMSX_LEVEL` - Field level
- `EMSX_LEN` - Field length

**`data/get_all_field_metadata.py` (117 lines)**

| Function | Description |
|----------|-------------|
| `main()` | Fetches all EMSX field metadata from Bloomberg API |

**Outputs:** CSV file with complete field reference

---

## Risk & Defect Analysis

### Security Vulnerabilities

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **JWT Secret in Code** | 🔴 High | `JWT_SECRET` default in scripts | Must generate strong secret in production |
| **Demo Account Credentials** | 🔴 High | Hardcoded demo passwords in `auth.py` | Change before production deployment |
| **No HTTPS** | 🟡 Medium | HTTP only (no TLS) | Deploy behind reverse proxy with TLS |
| **CORS Wildcard** | 🟡 Medium | `ALLOWED_ORIGINS` may be permissive | Restrict to known origins |
| **No Rate Limiting** | 🟡 Medium | API endpoints lack rate limiting | Add middleware for production |

### Performance Bottlenecks

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **Synchronous Bloomberg Calls** | 🟡 Medium | Some operations block event loop | Already wrapped with `run_in_executor` |
| **Large File Size** | 🟡 Medium | `main.py` is ~140KB | Consider modularization if growing |
| **Frontend Bundle Size** | 🟢 Low | 50+ UI components | Code splitting could help |
| **2-Second Polling** | 🟢 Low | High frequency polling | WebSocket upgrade implemented |
| **Memory Leaks** | 🟡 Medium | Cache without size limits | LRU policy implemented |

### Error Handling Gaps

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **Silent Failures** | 🟡 Medium | Some API errors may not surface | Add global error boundary |
| **No Retry Logic** | 🟡 Medium | Failed requests don't retry | Implement exponential backoff |
| **Missing Validation** | 🟢 Low | Some inputs not strictly validated | Add Zod schemas |
| **Bloomberg Disconnect** | 🔴 High | No automatic reconnection | Reconnect logic implemented |

### Maintainability Concerns

| Risk | Severity | Description | Mitigation |
|------|----------|-------------|------------|
| **Large Components** | 🟡 Medium | `OrderTable.tsx` (659 lines), `RouteTable.tsx` (788 lines) | Consider decomposition |
| **Type Duplication** | 🟢 Low | Types in both frontend and backend | Consider code generation |
| **Documentation Drift** | 🟡 Medium | Docs may not match code | Keep PROJECT_STRUCTURE.md updated |
| **Test Coverage** | 🔴 High | No automated tests | Add pytest and Jest tests |

### Known Issues (from HANDOFF.md)

| Issue | Status | Impact |
|-------|--------|--------|
| EMSX API Disabled in EMSS | 🔴 Open | Cannot connect to Bloomberg |
| EMSX_CURRENCY Field Invalid | 🟡 Partial | Currency field removed from subscription |
| Session Sharing Race Condition | 🟢 Fixed | Dedicated sessions per operation type |
| Status Mapping Incomplete | 🟢 Fixed | Added SENT, A-SENT, ROUTED, etc. |
| Broker Algorithm Refresh Empty | 🟢 Fixed | Exchange map updated |
| useBrokerAlgorithms Loading Stuck | 🟢 Fixed | Error state handled |

### Dependencies Risk Assessment

| Dependency | Version | Risk | Mitigation |
|------------|---------|------|------------|
| React | 19.2.0 | 🟢 Low | Latest stable |
| FastAPI | 0.109.0 | 🟢 Low | Stable, active |
| blpapi | 3.23.0 | 🟡 Medium | Bloomberg controlled |
| blpapi Python | 3.23.0 | 🟡 Medium | Requires Bloomberg Terminal |
| Tailwind | 3.4.19 | 🟢 Low | Stable, widely used |
| Radix UI | Various | 🟢 Low | Well maintained |

### Recommended Actions

1. **Immediate (High Priority)**
   - Generate strong JWT secret for production
   - Change demo account passwords
   - Enable HTTPS in production
   - Add basic rate limiting

2. **Short Term (Medium Priority)**
   - Add automated test suite (pytest + Jest)
   - Implement global error boundary
   - Add retry logic for failed API calls
   - Split large components

3. **Long Term (Low Priority)**
   - Add E2E testing with Playwright
   - Implement proper logging aggregation
   - Add performance monitoring
   - Consider GraphQL for API

---

## Quick Reference

### Development Commands

```powershell
# Backend
.\scripts\deploy\start-backend.ps1

# Frontend
.\scripts\deploy\start-frontend.ps1

# Or one-click launcher
.\scripts\deploy\launch-emsx.vbs
```

### Build Commands

```bash
# Frontend build
cd app && npm run build

# TypeScript check
cd app && npx tsc --noEmit

# Python syntax check
python -m py_compile emsx-backend/backend/main.py
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `http://localhost:3000/api/health` | Health check |
| `http://localhost:3000/api/docs` | Swagger UI |
| `http://localhost:5173` | Frontend (dev) |
| `http://localhost` | Frontend (Docker) |

---

*End of Document - Generated from actual codebase analysis*
