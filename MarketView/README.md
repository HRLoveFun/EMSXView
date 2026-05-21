# MarketView Module

> **Pre-Trade Analysis Module** · 🟡 Shell anchor only
> Market data analysis, instrument screening, and trade decision support

---

## Overview

The **MarketView** module provides pre-trade analysis capabilities to help traders make informed decisions before executing orders. This module is designed to be built incrementally as the platform evolves.

Current architecture note:

- The canonical frontend shell now exposes a MarketView anchor at `Execution/frontend/src/modules/marketview/MarketViewModule.tsx`.
- `MarketView/` remains the domain contract and documentation home for pre-trade capabilities.
- New MarketView functionality should plug into the shared frontend shell and shared logical data domain rather than introducing a second standalone UI by default.

## Phase 1 Delivery Plan

The first real MarketView slice is intentionally narrow:

1. Expose a read-only pre-trade market snapshot in the shared frontend shell.
2. Use the logical data-domain adapter layer instead of a direct deep import from the MarketView UI.
3. Start with stable day-level metrics that already exist in the CostView pipeline.

### First data boundary

The first MarketView data boundary is the latest `bdib_daily_summary` snapshot.

Current fields:

- `equ_ticker`
- `trade_date`
- `daily_close`
- `daily_volatility`
- `intraday_volatility`
- `total_volume`
- `adv_5d`
- `adv_20d`

### Why these fields first

- They are directly useful for pre-trade liquidity and volatility checks.
- They already exist in the live pipeline, so we can ship a real module without inventing a parallel data path.
- They are stable day-level data, which is a safer first step than introducing intraday streaming into MarketView immediately.

### How the data is obtained

1. Bloomberg daily history is fetched by CostView Stage 7 through `CostView/src/daily_metrics_calculator.py`.
2. The pipeline stores the derived daily summary in `bdib_daily_summary` inside the raw BDIB SQLite store.
3. `platform_data/adapters.py` exposes this through `MarketReferenceDataAdapter`.
4. `Execution/backend/api/routers/marketview.py` serves the snapshot at `/api/marketview/snapshot`.
5. `Execution/frontend/src/modules/marketview/MarketViewModule.tsx` renders the snapshot in the shared shell.

### Next increments

- Add symbol filtering and sort controls.
- Add liquidity warning thresholds on top of ADV and total volume.
- Add hand-off hooks so selected instruments can feed Execution workflows.
- Only after that, evaluate whether MarketView needs live streaming or richer order-aware pre-trade context.

## Planned Features

### Market Data Integration
- Real-time market data feeds
- Historical price data analysis
- Volume and liquidity metrics
- Market impact estimation

### Instrument Analysis
- Ticker screening and filtering
- Sector and industry classification
- Fundamental data integration
- Technical indicator calculations

### Pre-Trade Analytics
- ADV (Average Daily Volume) analysis
- Price volatility assessment
- Market depth visualization
- Optimal timing recommendations

### Risk Assessment
- Position sizing recommendations
- Portfolio exposure analysis
- Correlation analysis
- Value-at-Risk (VaR) calculations

## Code Location Convention

MarketView code currently lives inside `ExecutionView/` following the Shell + Module pattern:

| Layer        | Actual location                                                                 |
|--------------|----------------------------------------------------------------------------------|
| Frontend UI  | `ExecutionView/frontend/src/modules/marketview/MarketViewModule.tsx`             |
| Backend API  | `ExecutionView/backend/api/routers/marketview.py`                                |
| Data adapter | `platform_data/adapters.py` → `MarketReferenceDataAdapter`                       |
| Data source  | `DataPipeline/storage/repositories/` → `bdib_daily_summary` table               |

This directory (`MarketView/`) serves as the **domain contract and documentation home**
for pre-trade capabilities. It does not contain runnable code.

### Why this layout

- The shared frontend shell (`ExecutionView/frontend/`) mounts all business modules, not just ExecutionView.
- The shared backend assembly layer (`ExecutionView/backend/api/`) registers all domain routers.
- Keeping domain contracts here avoids deep coupling between modules while keeping a clear
  source-of-truth for MarketView capabilities and interfaces.

When MarketView complexity grows enough to warrant an independent build artifact,
it may be extracted into `MarketView/src/` and consumed via npm workspace. Until then,
this directory defines the contract; the code ships through the platform shell.

## Integration with Execution Module

MarketView will feed data into the Execution module through:

1. **Market Data API** - Real-time price and volume data
2. **Analytics API** - Calculated metrics and recommendations
3. **WebSocket** - Live updates for monitoring dashboard

## Future Roadmap

- [ ] Market data visualization components
- [ ] Instrument scanner with customizable filters
- [ ] Pre-trade risk checks
- [ ] Market impact prediction models
- [ ] Integration with Execution order entry

---

*This module is still early-stage, but the shell integration point now exists for incremental implementation.*
