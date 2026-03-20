# EMSX Order Field Analysis - Cache Persistence

## Summary of Fields and Cache Behavior

| Field | UI Column | Source | Merge Logic | Cached | Risk Level | Status |
|-------|-----------|--------|-------------|--------|------------|--------|
| **price** | Limit Px | EMSX原始数据 | `order.price if not None else cached.price` | ✅ Yes | Low | OK |
| **avgPrice** | Avg Px | EMSX原始数据 | `order.avgPrice or cached.avgPrice` | ✅ Yes | Low | OK |
| **arrivalPrice** | Arr Px | EMSX原始数据 | `order.arrivalPrice if not None else cached.arrivalPrice` | ✅ Yes | Low | OK |
| **lastPrice** | Last Px | Route数据 | `order.lastPrice if not None else cached.lastPrice` | ✅ Yes | Medium | OK |
| **mktVwap** | Ivl VWAP | Market Data计算 | `cached.mktVwap` | ✅ Yes | High | OK |
| **dollarValueUsd** | $Value | 计算 | `order.dollarValueUsd if not None else cached.dollarValueUsd` | ✅ Yes | High | FIXED |
| **pctChange** | %Change | Market Data计算 | `cached.pctChange` | ✅ Yes | **Critical** | FIXED |
| **adv5d** | ADV 5D | Market Data计算 | `cached.adv5d` | ✅ Yes | High | OK |
| **fxRate** | FX Rate | 计算 | `updates["fxRate"]` | ✅ Yes | Medium | OK |
| **currency** | Ccy | 计算/原始 | `auth_ccy` | ✅ Yes | Medium | OK |

## Changes Made

### 1. Fixed: dollarValueUsd not saved to cache
**Location:** `get_orders()` method around line 1804-1809

```python
# Added: Save enriched data back to cache
enriched_order = o.model_copy(update=updates) if updates else o
enriched.append(enriched_order)

# Save enriched data back to cache so future updates preserve calculated values
if updates:
    self._orders[o.id] = enriched_order
```

### 2. Fixed: pctChange not preserved during order merge
**Location:** Order merge logic around line 845-851

```python
# Added: Preserve pctChange from cached data
pctChange=cached.pctChange,  # preserved from market data enrichment
```

## How Fields Flow Through the System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Field Data Flow                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  EMSX Subscription                    Market Data (//blp/mktdata)           │
│  ─────────────────                    ───────────────────────────           │
│  price, avgPrice,                     pctChange, adv5d, mktVwap             │
│  arrivalPrice, status, etc.                                                 │
│       │                                    │                                │
│       ▼                                    ▼                                │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    _orders Cache (Dict)                       │          │
│  │  - Stores original EMSX fields                                │          │
│  │  - Stores enriched market data fields                         │          │
│  │  - Updated on each EMSX event (INIT_PAINT, NEW, UPDATE, etc.) │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                              │                                              │
│                              ▼                                              │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    get_orders() API Call                      │          │
│  │  - Reads from _orders cache                                   │          │
│  │  - Enriches: calculates dollarValueUsd, fxRate                │          │
│  │  - NOW SAVES: enriched data back to _orders cache (FIXED)     │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                              │                                              │
│                              ▼                                              │
│  ┌──────────────────────────────────────────────────────────────┐          │
│  │                    Frontend Display                           │          │
│  │  - Receives fully enriched order data                         │          │
│  │  - All columns should now display correctly                   │          │
│  └──────────────────────────────────────────────────────────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Testing Recommendations

1. **Test Order 4880806 (GLEN LN Equity)**
   - Check $Value is calculated correctly
   - Check Ivl VWAP displays correctly
   - Refresh multiple times to ensure values persist

2. **Test %Change Column**
   - Find an order with %Change value
   - Wait for EMSX update (or trigger one)
   - Verify %Change is still displayed (not reset to empty)

3. **Test All Enriched Fields**
   - Monitor orders with all fields populated
   - Verify values persist across:
     - Manual refresh
     - Auto-refresh (polling)
     - EMSX order updates

## Deployment

```powershell
cd c:\Users\hrchen\Documents\EMSX\emsx-backend
docker compose restart backend
```

Then verify in frontend that all columns display correctly.
