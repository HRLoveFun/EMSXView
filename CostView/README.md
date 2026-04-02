# CostView Module

> **Post-Trade Analysis Module**  
> Transaction cost analysis, performance reporting, and execution quality metrics

---

## Overview

The **CostView** module provides comprehensive post-trade analysis capabilities to evaluate execution performance and calculate transaction costs. This module is designed to be built incrementally as the platform evolves.

---

## FillFetch Component

**FillFetch** automatically retrieves fill records on a per-day basis according to a defined schema.

### Features

- **EMSX API Integration**: Fetches fill data via the Bloomberg EMSX History API
- **Deduplication**: Uses SHA-256 hash values to prevent duplicate local saves
- **SQL Tracking**: Maintains a SQLite table to track fetch history
- **Excel Export**: Saves fill data as Excel files for analysis

### Database Schema

The `fill_fetch_history` table tracks all fetch operations:

| Column | Type | Description |
|--------|------|-------------|
| `order_date` | TEXT | The date for which fills were fetched (YYYY-MM-DD) |
| `fetch_time` | TEXT | Time range of the fetch (e.g., "00:00:00-23:59:59") |
| `import_timestamp` | DATETIME | When the data was imported locally |
| `row_count` | INTEGER | Number of fill records in the fetched data |
| `hash_value` | TEXT | SHA-256 hash of the fetched data |
| `file_path` | TEXT | Path to saved Excel file |

### Installation

```bash
cd CostView
pip install -r requirements.txt
```

### Configuration

FillFetch uses a secure configuration system that **never hardcodes UUIDs**. The UUID is loaded from (in priority order):

1. **Environment Variable**: `EMSX_UUID` or `BLOOMBERG_UUID`
2. **Secure Credentials File**: `~/.config/fillfetch/credentials.json` (permission 0o600)
3. **External Provider**: Keyring, Vault, etc. (configurable)
4. **Interactive Prompt**: CLI will prompt if no UUID found

#### Setup

```bash
# Option 1: Environment variable (recommended for CI/CD)
set EMSX_UUID=your_uuid_here

# Option 2: Interactive setup (stores securely)
python -m src --setup-config

# Option 3: Validate configuration
python -m src --validate-config
```

#### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
# Bloomberg Configuration
BLOOMBERG_HOST=localhost
BLOOMBERG_PORT=8194

# FillFetch Configuration
FILLFETCH_DATA_DIR=./data/fills
FILLFETCH_DB_PATH=./data/fill_fetch_history.db

# Optional: UUID via environment (overrides credentials file)
# EMSX_UUID=your_uuid_here
```

### Usage

#### Command Line

```bash
# Setup UUID (interactive, stores securely)
python -m src --setup-config

# Validate configuration
python -m src --validate-config

# Fetch fills for a specific date (UUID from secure config)
python -m src --date 2024-01-15

# Fetch fills with explicit UUID (overrides config)
python -m src --date 2024-01-15 --uuid 1234

# Fetch fills for a date range
python -m src --start-date 2024-01-01 --end-date 2024-01-31

# Non-interactive mode (fails if UUID not configured)
python -m src --date 2024-01-15 --no-prompt

# View fetch history
python -m src --history

# View statistics
python -m src --stats
```

#### Python API

```python
from datetime import date
from src.fill_fetch import FillFetch
from src.secure_config import get_config_manager

# Initialize
fetcher = FillFetch()

# UUID is loaded securely from environment/credentials file
# No hardcoded values needed!
config = get_config_manager().get_uuid()
print(f"Using UUID: {config.uuid} (from {config.description})")

# Fetch fills for a single day (UUID auto-loaded from secure config)
result = fetcher.fetch_day(target_date=date(2024, 1, 15))
print(result)
# {
#     'order_date': '2024-01-15',
#     'success': True,
#     'rows_fetched': 50,
#     'hash_value': 'abc123...',
#     'file_path': './data/fills/fills_2024-01-15_1234_143022.xlsx'
# }

# Or explicitly provide UUID (overrides config)
result = fetcher.fetch_day(target_date=date(2024, 1, 15), uuid=1234)

# Fetch fills for a date range (UUID auto-loaded once)
results = fetcher.fetch_range(
    start_date=date(2024, 1, 1),
    end_date=date(2024, 1, 31)
)

# Get fetch history
history = fetcher.get_history()

# Get statistics
stats = fetcher.get_stats()

# Cleanup
fetcher.close()
```

### Procedure

FillFetch follows this procedure for each fetch:

1. **Fetch Data**: Given a `date_time` and `UUID`, fetch fill data from EMSX API
2. **Compute Hash**: Calculate SHA-256 hash of the fetched fill data table
3. **Check Duplicate**: Query SQL table for existing entry with same `order_date` and `hash_value`
   - If match found, skip remaining steps
4. **Save to Excel**: Write fill data to Excel file
5. **Update SQL Table**: Insert new fetch record with metadata

### Directory Structure

```
CostView/
├── README.md              # This file
├── requirements.txt       # Python dependencies
├── .env.example          # Environment variables template
├── src/
│   ├── __init__.py
│   ├── __main__.py       # CLI entry point
│   ├── fill_fetch.py     # Main FillFetch class
│   ├── database.py       # SQL database operations
│   ├── emsx_client.py    # Bloomberg EMSX API client
│   └── secure_config.py  # Secure UUID/credential management
├── tests/
│   └── test_fill_fetch.py # Unit tests
├── data/                 # Data directory (created at runtime)
│   ├── fill_fetch_history.db
│   └── fills/
│       └── fills_*.xlsx
└── ~/.config/fillfetch/  # Secure config (user home)
    └── credentials.json  # Permission 0o600
```

### Running Tests

```bash
python -m pytest tests/
```

---

## Planned Features

### Transaction Cost Analysis (TCA)
- Implementation Shortfall (IS) calculation
- VWAP slippage analysis
- Market impact measurement
- Timing cost evaluation

### Performance Reporting
- Execution quality metrics
- Benchmark comparisons (VWAP, TWAP, Arrival Price)
- Trader performance analytics
- Strategy effectiveness reports

### Cost Attribution
- Explicit cost tracking (commissions, fees)
- Implicit cost estimation (spread, market impact)
- Opportunity cost calculation
- Total cost of ownership analysis

### Visualization & Dashboards
- Cost breakdown charts
- Performance trend analysis
- Comparative analytics
- Custom report builder

---

## Data Requirements

### From Execution Module
- Order details (symbol, side, quantity, price)
- Route execution data
- Timestamps (creation, routing, fills)
- Broker and strategy information

### External Data
- Market prices (arrival, close)
- Volume data (ADV, daily volume)
- Benchmark data (VWAP, TWAP)

---

## Key Metrics

| Metric | Description | Formula |
|--------|-------------|---------|
| Implementation Shortfall | Difference between decision price and fill price | (Fill Price - Decision Price) / Decision Price |
| VWAP Slippage | Difference from volume-weighted average price | (Fill Price - VWAP) / VWAP |
| Market Impact | Price movement caused by the order | (Post-trade Price - Pre-trade Price) / Pre-trade Price |
| Participation Rate | Order size relative to market volume | Order Quantity / Market Volume |

---

## Integration with Execution Module

CostView will consume data from Execution through:

1. **REST API** - Historical order and route data
2. **Database** - Direct access to execution records
3. **Events** - Real-time fill notifications

---

## Future Roadmap

- [x] **FillFetch** - EMSX fill data fetcher with deduplication
- [ ] TCA calculation engine
- [ ] Performance dashboard
- [ ] Benchmark comparison tools
- [ ] Custom report generator
- [ ] Export capabilities (PDF, Excel)
- [ ] Alert system for cost anomalies

---
