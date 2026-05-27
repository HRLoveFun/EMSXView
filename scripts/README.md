# EMSXView Scripts Directory

Quick-launch batch files for local development workflows.

## Directory Layout

```
scripts/
├── ops/                    # Operational scripts (service management, data ops)
│   ├── service-manager.ps1    Primary service lifecycle manager
│   ├── import_excel_fills.py  Excel fill data importer
│   ├── sync-metrics.py         Post-trade metric synchronisation
│   └── cleanup-logs.ps1        Log rotation / purge
│
├── devtools/               # Developer tooling
│   ├── fetch_and_inspect.py        Data pipeline ad-hoc fetch tool
│   ├── run_attribution_notebook.py Attribution notebook runner
│   └── export-localstorage-cache.js  Browser storage cache export
│
├── deploy/                 # Deployment & environment setup
├── diagnose/               # Diagnostic / troubleshooting scripts
├── workflow/               # CI / refactoring automation
├── hooks/                  # Git hooks
├── mcp/                    # MCP knowledge server
│
├── *.bat                   # Root-level quick-launch shortcuts
│   ├── start-all.bat            Start all services
│   ├── stop-all.bat             Stop all services
│   ├── restart-all.bat          Restart all services
│   └── check-status.bat         Check service health
│
└── _archive/               # Archived / deprecated scripts
```

## Quick Reference

| Use case                          | Command                                      |
|-----------------------------------|----------------------------------------------|
| Start all services                | `start-all.bat` or `ops\service-manager.ps1` |
| Import Excel fills                | `python ops/import_excel_fills.py --dry-run`  |
| Run data diagnostic               | `python devtools/fetch_and_inspect.py`        |
| Clean log files                   | `ops\cleanup-logs.ps1`                       |
| Create desktop shortcuts          | `deploy\create-desktop-shortcut.ps1`          |
| Diagnose market data issues       | `python diagnose/diagnose_market_data.py`     |
