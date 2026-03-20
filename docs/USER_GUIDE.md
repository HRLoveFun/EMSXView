# EMSX Trading Tool — User Guide

> Operation manual for the EMSX Bloomberg Trading Workstation. Last updated: 2026-02-26.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start](#2-quick-start)
3. [Starting & Stopping](#3-starting--stopping)
4. [Interface Overview](#4-interface-overview)
5. [Monitor Tab](#5-monitor-tab)
6. [Orders Tab](#6-orders-tab)
7. [Routes Tab](#7-routes-tab)
8. [Batch Operations](#8-batch-operations)
9. [Filtering & Sorting](#9-filtering--sorting)
10. [Grouping](#10-grouping)
11. [Market Data Columns](#11-market-data-columns)
12. [Connection & Troubleshooting](#12-connection--troubleshooting)
13. [Configuration Reference](#13-configuration-reference)

---

## 1. Prerequisites

| Requirement | Details |
|-------------|---------|
| **OS** | Windows 10/11 |
| **Bloomberg Terminal** | Running and logged in on the same machine |
| **Bloomberg API** | Port 8194 accessible (default Terminal API port) |
| **Python** | 3.x with Anaconda (or `pip install -r requirements.txt`) |
| **Node.js** | 18+ (for frontend dev server) |
| **Browser** | Chrome / Edge (any modern browser) |

---

## 2. Quick Start

### One-Click Launch

Double-click **`launch-emsx.vbs`** (or the desktop shortcut created by `create-desktop-shortcut.ps1`).

This will:
1. Start the backend (FastAPI on port 3000)
2. Start the frontend (Vite dev server on port 5173)
3. Open your browser to `http://localhost:5173`

### Manual Launch

```powershell
# Terminal 1 — Backend
cd EMSX
.\start-backend.ps1

# Terminal 2 — Frontend
cd EMSX
.\start-frontend.ps1

# Open browser
start http://localhost:5173
```

### Desktop Shortcut

Run once to create a desktop shortcut:
```powershell
.\create-desktop-shortcut.ps1
```

---

## 3. Starting & Stopping

### Start Backend Only
```powershell
.\start-backend.ps1
# Or manually:
cd emsx-backend\backend
python main.py
```
The backend starts on **port 3000** and connects to Bloomberg automatically.

### Start Frontend Only
```powershell
.\start-frontend.ps1
# Or manually:
cd app
npm run dev
```
The frontend starts on **port 5173** with a proxy to the backend.

### Stop Services
- **Backend**: Close the PowerShell window, or press `Ctrl+C`
- **Frontend**: Close the PowerShell window, or press `Ctrl+C`
- **Both**: Close the launcher windows

### Force Kill (if port is stuck)
```powershell
# Kill backend on port 3000
Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  Where-Object { $_ -gt 0 } |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

---

## 4. Interface Overview

The application has three tabs and a toolbar:

```
┌──────────────────────────────────────────────────────────┐
│  🔄 EMSX Trading Tool    250 orders    ● Connected  退出  │  ← Toolbar
├──────────────────────────────────────────────────────────┤
│  [ Monitor ] [ Orders (250) ] [ Routes (291) ]           │  ← Tabs
├──────────────────────────────────────────────────────────┤
│                                                          │
│  (active tab content)                                    │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  EMSX Trading Tool v1.0.0          Bloomberg Terminal    │  ← Footer
└──────────────────────────────────────────────────────────┘
```

### Toolbar Elements

| Element | Description |
|---------|-------------|
| **Refresh button** (🔄) | Force-refresh all orders from Bloomberg |
| **Order count** | Shows count for the active tab (filtered for Orders, flagged for Monitor) |
| **Connection indicator** | Green = connected, Red = disconnected (checks every 30s) |
| **退出 (Logout)** | End session (only relevant if JWT auth is enabled) |

### Auto-Refresh

All data refreshes automatically every **1 second** — no manual action needed. The UI updates atomically so all columns stay in sync.

---

## 5. Monitor Tab

The Monitor tab is a **risk/alert dashboard** that highlights orders requiring attention.

### Alert Conditions

An order appears on the Monitor board if ANY of these conditions are met:

| Flag | Condition | Color |
|------|-----------|-------|
| **$Value Low** | USD dollar value < $10,000 | Orange |
| **$Value High** | USD dollar value > $49,000,000 | Red |
| **%Chg ↑ (BUY)** | Stock price change > +4.5% AND side is BUY | Red |
| **%Chg ↓ (SELL)** | Stock price change < -4.5% AND side is SELL | Red |
| **ADV > 5%** | Order quantity / 5-day avg volume > 5% | Yellow |

### Monitor Features

- **Flag badges**: Each flagged condition shows as a colored badge
- **$Value column**: Shows USD value (converted via real-time FX rates)
- **Group by**: Group flagged orders by exchange, status, side, portfolio, trader, or currency
- **Collapsible groups**: Click group headers to expand/collapse
- **Sort**: Click any column header to sort ascending/descending

---

## 6. Orders Tab

The Orders tab shows **all EMSX orders** with full detail.

### Column Reference

| Column | Source | Description |
|--------|--------|-------------|
| ☐ | — | Checkbox for batch selection |
| Seq | EMSX_SEQUENCE | Order sequence number (unique ID) |
| Ticker | EMSX_TICKER | Bloomberg ticker (e.g., `AAPL US Equity`) |
| Side | EMSX_SIDE | BUY (green) or SELL (red) |
| Status | EMSX_STATUS | Order status badge |
| Qty | EMSX_AMOUNT | Total order quantity |
| Filled | EMSX_FILLED | Shares filled |
| %Filled | Computed | `(filled / qty) × 100` |
| Avg Px | EMSX_AVG_PRICE | Average fill price |
| Limit Px | EMSX_LIMIT_PRICE | Limit price |
| %Remain | EMSX_PERCENT_REMAIN | Remaining percentage |
| %Change | CHG_PCT_1D | 1-day price change (from mktdata) |
| ADV 5D | VOLUME_AVG_5D | 5-day average daily volume (from mktdata) |
| $Value | Computed | USD value = qty × price × FX rate |
| Ivl VWAP | VWAP | Intraday VWAP (from mktdata) |
| Day Avg | EMSX_DAY_AVG_PRICE | Day average price |
| TIF | EMSX_TIF | Time in force (DAY, GTC, etc.) |
| Type | EMSX_ORDER_TYPE | Order type (LIMIT, MARKET, etc.) |
| Exch | EMSX_EXCHANGE | Exchange |
| Ccy | Currency | Trading currency |
| Portfolio | EMSX_PORT_NAME | Portfolio name |
| Trader | EMSX_TRADER | Trader ID |
| Broker | EMSX_BROKER | Broker |
| Strat | EMSX_STRATEGY_TYPE | Strategy type |
| Rate | EMSX_STRATEGY_PART_RATE1 | Strategy participation rate |
| PM Notes | Combined | Strategy + custom notes concatenated |
| Account | EMSX_ACCOUNT | Account |

### Status Colors

| Status | Color |
|--------|-------|
| NEW | Blue |
| WORKING | Green |
| PARTIAL | Yellow |
| FILLED | Green (bright) |
| CANCELLED | Gray |
| COMPLETED | Green |
| QUEUED | Purple |
| SUSPENDED | Orange |

---

## 7. Routes Tab

The Routes tab shows **execution-level route data** for all orders.

### Key Columns

| Column | Description |
|--------|-------------|
| Seq.Route | `{EMSX_SEQUENCE}.{EMSX_ROUTE_ID}` composite key |
| Ticker | Parent order ticker (enriched from order cache) |
| Side | Parent order side |
| Status | Route status (SENT, WORKING, PARTFILLED, FILLED, CANCEL, etc.) |
| Broker | Execution broker |
| Amount / Filled / Working | Route-level quantities |
| Avg Px / Limit Px | Prices |
| Day Avg / Day Fill | Intraday fill stats |
| Strategy | Strategy type + style |
| Destination | Exchange destination |
| Last Fill | Last fill date/time + size |
| Reason | Reason code + description (for rejections/cancels) |
| Commission | Commission rate + broker commission |

### Route Features

- **Sorting**: Click any column header
- **Grouping**: Group by ticker, broker, status, or portfolio
- **Internal filters**: Filter by status, broker, or ticker within the route view

---

## 8. Batch Operations

Select multiple orders in the Orders tab, then use the batch panel at the bottom:

1. **Select orders**: Click checkboxes, or use "Select All" in the header
2. **Choose action**:
   - **Modify Price** — set new limit price for all selected
   - **Modify Quantity** — set new quantity for all selected
   - **Modify TIF** — change time-in-force
   - **Cancel** — cancel all selected orders (requires double confirmation)
3. **Confirm**: Review the count and click Submit
4. **Result**: Toast notification shows success/failure count

> ⚠️ Batch operations send real Bloomberg ModifyOrderEx / CancelOrderEx requests. They are **irreversible**.

---

## 9. Filtering & Sorting

### In-Header Filters (Orders Tab)

Click the filter icon (🔍) on any column header to open a filter popover:

| Filter | Type | Example |
|--------|------|---------|
| *Ticker* | Text search | Type "AAPL" → shows matching tickers |
| *Side* | Toggle | Click BUY or SELL |
| *Status* | Multi-select | Check WORKING + PARTIAL |
| *Type* | Multi-select | Check LIMIT + MARKET |
| *Portfolio* | Text search | Type portfolio name |
| *Trader* | Multi-select | Check one or more traders |
| *Exchange* | Text search | Type exchange code |
| *Currency* | Text search | Type "USD" |

Filters are applied **instantly** (client-side, no network call).

### Sorting

- Click any column header to sort ascending
- Click again to sort descending
- Sort indicator (▲/▼) shows current sort column and direction

---

## 10. Grouping

All three tabs support **group-by** functionality:

1. Click the **Group by** dropdown (top-right of the table)
2. Select a grouping field (e.g., Exchange, Status, Trader, Portfolio, Side, Currency)
3. Orders/routes are grouped under collapsible headers showing the group value and count
4. Click a group header to expand/collapse
5. Select **"None"** to remove grouping

---

## 11. Market Data Columns

Three columns are sourced from Bloomberg `//blp/mktdata` streaming subscriptions (not EMSX):

| Column | Bloomberg Field | Update Frequency |
|--------|----------------|-----------------|
| **%Change** | `CHG_PCT_1D` | Real-time (every tick) |
| **ADV 5D** | `VOLUME_AVG_5D` | Real-time |
| **Ivl VWAP** | `VWAP` | Real-time |

### FX Rates & $Value

- FX rates stream from `//blp/mktdata` for each non-USD currency (e.g., `JPYUSD Curncy`)
- **$Value (USD)** = order quantity × price × FX rate to USD
- When FX data is unavailable, $Value shows "—"

### Automatic Retry

- If Bloomberg daily capacity is exhausted, subscriptions fail temporarily
- The system **automatically retries** every 5 minutes
- When capacity resets (next business day), data starts flowing with no action required

---

## 12. Connection & Troubleshooting

### Connection Status

The toolbar shows a colored badge:
- 🟢 **Connected** — Bloomberg API is reachable and sessions are active
- 🔴 **Disconnected** — connection lost

### Reconnect

Click **Reconnect** in the toolbar, or restart the backend. The system auto-reconnects on the next API call.

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Backend unavailable" | Backend not running | Run `.\start-backend.ps1` |
| "Cannot reach backend" | Port 3000 blocked or backend crashed | Check terminal for errors; restart |
| "$Value shows 0 / —" | FX rates not loaded (daily capacity limit) | Wait for Bloomberg reset or restart next day |
| "%Change / ADV 5D show 0" | Market data subscription failed | Check logs; system retries every 5 min |
| "Subscription failed" | Bloomberg Terminal not logged in | Log in to Bloomberg Terminal first |
| Port 3000 stuck | Old process didn't shut down | Use force-kill command (see section 3) |
| Empty order list | EMSX has no active orders | Check Bloomberg EMSX blotter directly |
| Orders appear slowly | Initial snapshot loading | Wait 3-5 seconds after startup |

### Logs

Backend logs are written to:
- **Console**: stdout in the backend terminal window
- **File**: `emsx-backend/backend/logs/emsx_api.log`

Check logs for subscription status, connection errors, or data flow issues:
```powershell
# View last 50 lines
Get-Content emsx-backend\backend\logs\emsx_api.log -Tail 50

# Search for errors
Select-String -Path emsx-backend\backend\logs\emsx_api.log -Pattern "ERROR|WARNING" | Select-Object -Last 20
```

---

## 13. Configuration Reference

### Backend (`emsx-backend/.env`)

```env
# Bloomberg
BLOOMBERG_HOST=localhost       # Bloomberg API host
BLOOMBERG_PORT=8194            # Bloomberg API port

# API Server
API_HOST=0.0.0.0              # Listen address
API_PORT=3000                  # Listen port
API_WORKERS=1                  # Uvicorn workers (keep at 1 for Bloomberg)

# Security
JWT_SECRET=your-secret-key     # JWT signing secret
JWT_EXPIRE_MINUTES=480         # Token TTL (8 hours)

# CORS
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:80
```

### Frontend (`app/.env`)

```env
VITE_API_URL=                  # Empty = use Vite proxy (recommended for dev)
VITE_USE_MOCK=false            # Mock mode (not implemented)
```

### Vite Proxy (Development)

In dev mode, the Vite dev server proxies API calls:
- `/api/*` → `http://localhost:3000`
- `/ws/*` → `ws://localhost:3000`

This avoids CORS issues during development. In production (Docker/Nginx), Nginx handles routing.
