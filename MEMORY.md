# Project Memory

> Architectural decisions, API contracts, and design patterns.
> Update when making significant structural changes.

---

## Architecture Overview

```
┌─────────────────┐     HTTP/WS      ┌──────────────────┐     blpapi     ┌─────────────┐
│  React Frontend │ ◄───────────────► │  FastAPI Backend │ ◄─────────────► │  Bloomberg  │
│   (Port 5173)   │                   │   (Port 3000)    │               │    EMSX     │
└─────────────────┘                   └──────────────────┘               └─────────────┘
```

---

## Key Design Decisions

### 1. Backend Architecture (FastAPI + blpapi)

**Decision**: Single `main.py` file vs. modular structure
- **Rationale**: Trading system requires tight coordination; modular may obscure flow
- **Tradeoff**: ~140KB file is large but keeps all EMSX logic centralized
- **When to reconsider**: If adding multiple trading strategies (split by strategy module)

**Decision**: Async session management with threading for Bloomberg
- **Rationale**: Bloomberg blpapi requires event loop; FastAPI needs async
- **Pattern**: `asyncio` + `threading.Thread` for subscription loops
- **See**: `main.py` session lifecycle methods

### 2. Field Subscription Strategy

**Active Fields** (as of 2026-02-24):
```python
API_SEQ_NUM, EMSX_SEQUENCE, EMSX_TICKER, EMSX_SIDE, EMSX_AMOUNT,
EMSX_FILLED, EMSX_STATUS, EMSX_ORDER_TYPE, EMSX_LIMIT_PRICE,
EMSX_STOP_PRICE, EMSX_AVG_PRICE, EMSX_TIF, EMSX_ACCOUNT,
EMSX_TRADER, EMSX_NOTES, EMSX_DATE, EMSX_TIME_STAMP,
EMSX_EXCHANGE, EMSX_ISIN, EMSX_SEC_NAME, EMSX_WORKING
```

**Known Issue**: `EMSX_CURRENCY` invalid — removed from subscription
- **Source**: Bloomberg logs: `Error: Invalid field name detected. Field=|EMSX_CURRENCY|`
- **Action**: Cross-reference GUIDE for correct currency field (may be `EMSX_CRNCY` or similar)

### 3. Frontend Component Strategy

**Decision**: shadcn/ui + Radix primitives
- **Rationale**: Rapid development, accessible, themeable
- **Structure**: `sections/` for page blocks, `components/ui/` for primitives
- **Key Components**:
  - `OrderTable.tsx` — Primary order management grid
  - `RouteTable.tsx` — Route modification UI
  - `MonitorBoard.tsx` — Real-time position monitoring

**State Management**: React hooks + context (no Redux/Zustand yet)
- **Rationale**: Current complexity doesn't warrant global state library
- **When to reconsider**: >5 shared state slices or complex async flows

### 4. API Contract

**Backend Endpoints** (from `main.py`):
```
GET  /api/health          → Health check
GET  /api/connection      → Bloomberg connection status
GET  /api/orders          → List all orders
POST /api/orders          → Create new order
GET  /api/routes          → List routes
POST /api/routes/modify   → Modify route
WS   /ws                  → WebSocket for real-time updates
```

**TypeScript Types** (`app/src/types/index.ts`):
- `Order`, `Route`, `EMSXMessage`, `ConnectionStatus`
- Keep in sync with Pydantic models in `main.py`

### 5. Environment Configuration

**Required Variables** (`.env`):
```
BLOOMBERG_HOST=localhost
BLOOMBERG_PORT=8194
BLOOMBERG_TIMEOUT=30000
API_HOST=0.0.0.0
API_PORT=3000
JWT_SECRET=<generate>
```

**File Location**: `emsx-backend/backend/.env` (gitignored)

---

## Patterns & Conventions

### Python Backend
- **Logging**: Structured logs to `logs/emsx_api.log` with rotation
- **Error Handling**: `HTTPException` for API errors, try/except for Bloomberg calls
- **Type Safety**: Pydantic models for all request/response schemas

### TypeScript Frontend
- **API Client**: `app/src/services/api.ts` — axios wrapper with auto-mock fallback
- **Formatting**: `app/src/lib/format-utils.ts` — currency, number, date formatters
- **Styling**: Tailwind + `class-variance-authority` for component variants

### EMSX API Patterns
- **Service Fallback**: `//blp/emapisvc` → `//blp/emapisvc_beta` on failure
- **Subscription Model**: Topic-based with field filtering
- **Order Lifecycle**: NEW → WORKING → PARTIAL_FILL → FILLED

---

## Integration Points

### Bloomberg Terminal
- **Host**: `localhost:8194` (default EMSX API port)
- **Service**: `//blp/emapisvc` (production), `//blp/emapisvc_beta` (test)
- **Requirement**: Terminal must have EMSX API enabled in EMSS configuration

### Internal AutoRoute System
- **URL**: `http://bstapp:50036/Trading/AutoRoute`
- **Purpose**: IT-managed broker routing UI
- **Goal**: Automate route button clicks via API integration

---

## Known Limitations

1. **EMSX API Disabled**: Backend cannot connect until IT enables API in Bloomberg terminal
2. **Field Validation**: Some field names may not match GUIDE (e.g., EMSX_CURRENCY)
3. **No Production Auth**: JWT implementation present but not hardened for production
4. **Single Bloomberg Session**: No failover to secondary terminal

---

## References

- **GUIDE**: `EMSX API Developer's Guide.html` — authoritative for all API contracts
- **Field Metadata**: `emsx_field_metadata.csv` — extracted field reference
- **Implementation Notes**: `ODD_LOT_IMPLEMENTATION.md`, `ROUTE_MODIFY_FEATURES.md`
