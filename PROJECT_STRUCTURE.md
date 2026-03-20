# EMSX Project Structure

> Clean, organized folder structure for the EMSX Trading Platform.
> Last reorganized: 2026-03-18

---

## Root Directory

Core project files that should always be visible at the top level:

| File | Purpose |
|------|---------|
| `README.md` | Project overview and quick start |
| `CLAUDE.md` | Claude Code instructions (executable format) |
| `HANDOFF.md` | Session continuity log |
| `MEMORY.md` | Architectural decisions and design patterns |
| `PROJECT_STRUCTURE.md` | This file - project organization documentation |
| `.gitignore` | Git ignore rules |

---

## Folder Structure

```
EMSX/
├── README.md, CLAUDE.md, HANDOFF.md, MEMORY.md, PROJECT_STRUCTURE.md  # Core docs
├── .gitignore                                    # Git config
│
├── app/                          # React frontend (Vite + TypeScript + Tailwind)
│   ├── src/
│   │   ├── App.tsx               # Main app component with tab routing
│   │   ├── App.css               # App-specific styles
│   │   ├── index.css             # Global styles
│   │   ├── main.tsx              # Entry point
│   │   │
│   │   ├── sections/             # Main UI sections (per UI spec)
│   │   │   ├── Toolbar.tsx               # Header with refresh, connection status
│   │   │   ├── MonitorBoard.tsx          # Alert conditions + flagged orders
│   │   │   ├── ExecutionBoard.tsx        # Container for Orders/Routes tabs
│   │   │   ├── OrderTable.tsx            # Orders table with filters/grouping
│   │   │   ├── RouteTable.tsx            # Routes table with actions
│   │   │   ├── BatchOperationPanel.tsx   # Batch modify selected orders
│   │   │   ├── SettingsBoard.tsx         # Settings: algorithms + frequencies
│   │   │   └── ToastContainer.tsx        # Toast notifications
│   │   │
│   │   ├── components/           # Reusable components
│   │   │   ├── route-action-menu.tsx     # Route row action dropdown
│   │   │   ├── route-modify-dialogs.tsx  # Route modification dialogs
│   │   │   ├── strategy-data-manager.tsx # Import/export strategy config
│   │   │   └── ui/                       # shadcn/ui components (50+ files)
│   │   │
│   │   ├── hooks/                # Custom React hooks
│   │   │   └── use-mobile.ts     # Mobile detection hook
│   │   │
│   │   ├── lib/                  # Utility libraries
│   │   │   ├── utils.ts                  # General utilities
│   │   │   ├── format-utils.ts           # Number/date formatting
│   │   │   ├── monitor-conditions.ts     # Alert condition logic
│   │   │   ├── table-constants.ts        # Grouping/filtering options
│   │   │   └── cache-manager.ts          # Caching utilities
│   │   │
│   │   ├── services/             # API services
│   │   │   ├── api.ts                    # Main API service
│   │   │   └── strategy-data-service.ts  # Strategy file management
│   │   │
│   │   └── types/                # TypeScript type definitions
│   │       └── index.ts                  # All type exports
│   │
│   ├── public/                   # Static assets
│   │   └── strategy-data/        # Strategy JSON files
│   │       ├── default-strategies.json
│   │       ├── default-strategy-params.json
│   │       └── EXPORT_EXAMPLE.json
│   │
│   ├── dist/                     # Build output
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.js
│
├── emsx-backend/                 # Python FastAPI backend
│   ├── backend/
│   └── config/
│
├── scripts/                      # Utility scripts
│   ├── diagnose/                 # Diagnostic/debug scripts
│   │   ├── diagnose_market_data.py
│   │   ├── diagnose_odd_lot.py
│   │   ├── diagnose_order.py
│   │   └── test_hash.py
│   └── deploy/                   # Deployment scripts
│       ├── start-backend.ps1
│       ├── start-frontend.ps1
│       ├── create-desktop-shortcut.ps1
│       ├── fix-copilot-h2.ps1
│       └── launch-emsx.vbs
│
├── docs/                         # Documentation
│   ├── reference/                # External references
│   │   └── EMSX_API_Guide.md     # Bloomberg API guide
│   ├── features/                 # Feature documentation
│   │   └── route-modify/
│   │       ├── spec.md
│   │       └── implementation.md
│   └── FRONTEND_UI_DESCRIPTION.md        # UI specification (source of truth)
│
├── data/                         # Data files
│   ├── emsx_field_metadata.csv
│   └── get_all_field_metadata.py
│
├── archive/                      # Archived/outdated docs
│   └── ... (9 files)
│
└── logs/                         # Runtime logs
```

---

## Key Changes Made

### Archived (moved to `archive/`)
Outdated task-result documentation that has been superseded:

- `FIELD_ANALYSIS.md` — Cache fix analysis (completed)
- `ODD_LOT_*.md` (×4 files) — Odd lot detection implementations (completed)
- `PROJECT_ANALYSIS.md` — Code audit with "FIXED" markers
- `OPTIMIZATION_SUMMARY.md` — Completed optimization summary
- Alternative API guide formats (HTML, MHTML, PDF)

### Organized (moved to appropriate folders)

| Original Location | New Location | Purpose |
|-------------------|--------------|---------|
| `diagnose_*.py` | `scripts/diagnose/` | Diagnostic utilities |
| `start-*.ps1` | `scripts/deploy/` | Deployment scripts |
| `emsx_field_metadata.csv` | `data/` | Reference data |
| `ROUTE_MODIFY_*.md` | `docs/features/route-modify/` | Feature docs |
| `EMSX API Guide.md` | `docs/reference/` | External reference |

---

## Quick Reference

### Start Development
```powershell
# Backend
.\scripts\deploy\start-backend.ps1

# Frontend
.\scripts\deploy\start-frontend.ps1

# Or use VBScript launcher
.\scripts\deploy\launch-emsx.vbs
```

### Run Diagnostics
```powershell
python scripts\diagnose\diagnose_order.py
python scripts\diagnose\diagnose_market_data.py
python scripts\diagnose\diagnose_odd_lot.py
```

### API Documentation
- Primary: `docs/reference/EMSX_API_Guide.md`
- Archived formats: `archive/EMSX API Developer's Guide.*`

---

## Maintenance Notes

- **Add new scripts** to `scripts/` subfolders by purpose
- **Archive completed task docs** to `archive/` (don't delete)
- **Feature specs** go in `docs/features/<feature-name>/`
- **Reference data** goes in `data/`

---

## Frontend UI Alignment (2026-03-18)

The frontend structure has been aligned with `docs/FRONTEND_UI_DESCRIPTION.md`:

### Tab Structure
| Tab | Content |
|-----|---------|
| **Monitor** | MonitorBoard with alert conditions and flagged orders |
| **Execution** | ExecutionBoard containing Orders and Routes sub-tabs |
| **Settings** | SettingsBoard with global settings, broker algorithms, parameter frequencies |

### Key Components per UI Spec
- **Toolbar** (`sections/Toolbar.tsx`) - App title, order count, connection status, refresh, logout
- **MonitorBoard** (`sections/MonitorBoard.tsx`) - Condition panel, subgroup by, order table with flags
- **ExecutionBoard** (`sections/ExecutionBoard.tsx`) - Orders/Routes sub-tab container
- **OrderTable** (`sections/OrderTable.tsx`) - 23 columns, filtering, grouping, selection
- **RouteTable** (`sections/RouteTable.tsx`) - 21 columns, two-level grouping, route actions
- **BatchOperationPanel** (`sections/BatchOperationPanel.tsx`) - Batch modify modal
- **SettingsBoard** (`sections/SettingsBoard.tsx`) - Global toggles, broker algorithm tree, parameter table, frequency table
- **ToastContainer** (`sections/ToastContainer.tsx`) - Success/error/info notifications

### Strategy Data Manager
Moved from Toolbar to Settings (per UI spec section 7). Accessible via "Strategy Data Manager" button in Broker Algorithm Configuration section.
