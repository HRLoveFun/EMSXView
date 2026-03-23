# Migration Guide

> **Project Restructure: Before/After File Mapping**

---

## Overview

This document provides a complete mapping between the old project structure and the new modular architecture.

## Directory Mapping

### Root Level Changes

| Old Path | New Path | Module |
|----------|----------|--------|
| `README.md` | `README.md` | Root (updated) |
| `PROJECT_STRUCTURE.md` | `docs/PROJECT_STRUCTURE.md` | docs |
| `CLAUDE.md` | `docs/CLAUDE.md` | docs |
| `HANDOFF.md` | `docs/HANDOFF.md` | docs |
| `MEMORY.md` | `docs/MEMORY.md` | docs |
| `EXPORT_FEATURE_GUIDE.md` | `docs/EXPORT_FEATURE_GUIDE.md` | docs |
| `LOG_OPTIMIZATION_SUMMARY.md` | `docs/LOG_OPTIMIZATION_SUMMARY.md` | docs |
| `STRATEGY_FILE_STORAGE_SUMMARY.md` | `docs/STRATEGY_FILE_STORAGE_SUMMARY.md` | docs |

### Execution Module (Consolidated Codebase)

#### Frontend

| Old Path | New Path |
|----------|----------|
| `app/README.md` | `Execution/frontend/README.md` |
| `app/package.json` | `Execution/frontend/package.json` |
| `app/vite.config.ts` | `Execution/frontend/vite.config.ts` |
| `app/tsconfig.json` | `Execution/frontend/tsconfig.json` |
| `app/tsconfig.app.json` | `Execution/frontend/tsconfig.app.json` |
| `app/tsconfig.node.json` | `Execution/frontend/tsconfig.node.json` |
| `app/tailwind.config.js` | `Execution/frontend/tailwind.config.js` |
| `app/postcss.config.js` | `Execution/frontend/postcss.config.js` |
| `app/eslint.config.js` | `Execution/frontend/eslint.config.js` |
| `app/components.json` | `Execution/frontend/components.json` |
| `app/index.html` | `Execution/frontend/index.html` |
| `app/Dockerfile` | `Execution/frontend/Dockerfile` |
| `app/.dockerignore` | `Execution/frontend/.dockerignore` |
| `app/.env` | `Execution/frontend/.env` |
| `app/.env.example` | `Execution/frontend/.env.example` |
| `app/.gitignore` | `Execution/frontend/.gitignore` |
| `app/info.md` | `Execution/frontend/info.md` |

#### Frontend Source Code

| Old Path | New Path |
|----------|----------|
| `app/src/main.tsx` | `Execution/frontend/src/main.tsx` |
| `app/src/App.tsx` | `Execution/frontend/src/App.tsx` |
| `app/src/App.css` | `Execution/frontend/src/App.css` |
| `app/src/index.css` | `Execution/frontend/src/index.css` |
| `app/src/types/index.ts` | `Execution/frontend/src/types/index.ts` |
| `app/src/services/api.ts` | `Execution/frontend/src/services/api.ts` |
| `app/src/services/strategy-data-service.ts` | `Execution/frontend/src/services/strategy-data-service.ts` |
| `app/src/hooks/use-mobile.ts` | `Execution/frontend/src/hooks/use-mobile.ts` |
| `app/src/hooks/use-broker-algorithms.ts` | `Execution/frontend/src/hooks/use-broker-algorithms.ts` |
| `app/src/lib/utils.ts` | `Execution/frontend/src/lib/utils.ts` |
| `app/src/lib/format-utils.ts` | `Execution/frontend/src/lib/format-utils.ts` |
| `app/src/lib/cache-manager.ts` | `Execution/frontend/src/lib/cache-manager.ts` |
| `app/src/lib/monitor-conditions.ts` | `Execution/frontend/src/lib/monitor-conditions.ts` |
| `app/src/lib/table-constants.ts` | `Execution/frontend/src/lib/table-constants.ts` |
| `app/src/components/ui/*` | `Execution/frontend/src/components/ui/*` |
| `app/src/components/order-modify-dialog.tsx` | `Execution/frontend/src/components/order-modify-dialog.tsx` |
| `app/src/components/order-route-dialog.tsx` | `Execution/frontend/src/components/order-route-dialog.tsx` |
| `app/src/components/route-action-menu.tsx` | `Execution/frontend/src/components/route-action-menu.tsx` |
| `app/src/components/route-modify-dialogs.tsx` | `Execution/frontend/src/components/route-modify-dialogs.tsx` |
| `app/src/components/strategy-data-manager.tsx` | `Execution/frontend/src/components/strategy-data-manager.tsx` |
| `app/src/sections/Toolbar.tsx` | `Execution/frontend/src/sections/Toolbar.tsx` |
| `app/src/sections/MonitorBoard.tsx` | `Execution/frontend/src/sections/MonitorBoard.tsx` |
| `app/src/sections/LazyOrderBoard.tsx` | `Execution/frontend/src/sections/LazyOrderBoard.tsx` |
| `app/src/sections/ExecutionBoard.tsx` | `Execution/frontend/src/sections/ExecutionBoard.tsx` |
| `app/src/sections/OrderTable.tsx` | `Execution/frontend/src/sections/OrderTable.tsx` |
| `app/src/sections/RouteTable.tsx` | `Execution/frontend/src/sections/RouteTable.tsx` |
| `app/src/sections/BatchOperationPanel.tsx` | `Execution/frontend/src/sections/BatchOperationPanel.tsx` |
| `app/src/sections/SettingsBoard.tsx` | `Execution/frontend/src/sections/SettingsBoard.tsx` |
| `app/src/sections/ToastContainer.tsx` | `Execution/frontend/src/sections/ToastContainer.tsx` |
| `app/public/strategy-data/*` | `Execution/frontend/public/strategy-data/*` |
| `app/dist/*` | `Execution/frontend/dist/*` |

#### Backend

| Old Path | New Path |
|----------|----------|
| `emsx-backend/README.md` | `Execution/backend/README.md` |
| `emsx-backend/QUICKSTART.md` | `Execution/backend/QUICKSTART.md` |
| `emsx-backend/docker-compose.yml` | `Execution/backend/docker-compose.yml` |
| `emsx-backend/docker-compose.host.yml` | `Execution/backend/docker-compose.host.yml` |
| `emsx-backend/.env` | `Execution/backend/.env` |
| `emsx-backend/.env.example` | `Execution/backend/.env.example` |
| `emsx-backend/.gitignore` | `Execution/backend/.gitignore` |
| `emsx-backend/.dockerignore` | `Execution/backend/.dockerignore` |
| `emsx-backend/backend/main.py` | `Execution/backend/api/main.py` |
| `emsx-backend/backend/auth.py` | `Execution/backend/api/auth.py` |
| `emsx-backend/backend/start_server.py` | `Execution/backend/api/start_server.py` |
| `emsx-backend/backend/requirements.txt` | `Execution/backend/api/requirements.txt` |
| `emsx-backend/backend/Dockerfile` | `Execution/backend/api/Dockerfile` |
| `emsx-backend/backend/.dockerignore` | `Execution/backend/api/.dockerignore` |
| `emsx-backend/config/nginx.conf` | `Execution/backend/config/nginx.conf` |
| `emsx-backend/config/nginx-host.conf` | `Execution/backend/config/nginx-host.conf` |
| `emsx-backend/config/prometheus.yml` | `Execution/backend/config/prometheus.yml` |
| `emsx-backend/config/grafana/*` | `Execution/backend/config/grafana/*` |
| `emsx-backend/scripts/deploy.sh` | `scripts/deploy/deploy.sh` |
| `emsx-backend/scripts/setup-windows.ps1` | `scripts/deploy/setup-windows.ps1` |
| `emsx-backend/logs/*` | `Execution/backend/logs/*` |

### Scripts (Consolidated)

| Old Path | New Path |
|----------|----------|
| `scripts/cleanup-logs.ps1` | `scripts/cleanup-logs.ps1` |
| `scripts/export-localstorage-cache.js` | `scripts/export-localstorage-cache.js` |
| `scripts/deploy/start-backend.ps1` | `scripts/deploy/start-backend.ps1` |
| `scripts/deploy/start-frontend.ps1` | `scripts/deploy/start-frontend.ps1` |
| `scripts/deploy/launch-emsx.vbs` | `scripts/deploy/launch-emsx.vbs` |
| `scripts/deploy/create-desktop-shortcut.ps1` | `scripts/deploy/create-desktop-shortcut.ps1` |
| `scripts/diagnose/diagnose_order.py` | `scripts/diagnose/diagnose_order.py` |
| `scripts/diagnose/diagnose_market_data.py` | `scripts/diagnose/diagnose_market_data.py` |
| `scripts/diagnose/diagnose_odd_lot.py` | `scripts/diagnose/diagnose_odd_lot.py` |
| `scripts/diagnose/test_hash.py` | `scripts/diagnose/test_hash.py` |

### Documentation (Consolidated)

| Old Path | New Path |
|----------|----------|
| `docs/ERROR_PATTERNS.md` | `docs/ERROR_PATTERNS.md` |
| `docs/USER_GUIDE.md` | `docs/USER_GUIDE.md` |
| `docs/FRONTEND_UI_DESCRIPTION.md` | `docs/FRONTEND_UI_DESCRIPTION.md` |
| `docs/KNOWLEDGE_WORKFLOW.md` | `docs/KNOWLEDGE_WORKFLOW.md` |
| `docs/SESSION_DIGEST.md` | `docs/SESSION_DIGEST.md` |
| `docs/strategy-file-storage.md` | `docs/strategy-file-storage.md` |
| `docs/reference/EMSX-API-Complete-Guide.md` | `docs/reference/EMSX-API-Complete-Guide.md` |
| `docs/reference/EMSX-API-Quick-Reference.md` | `docs/reference/EMSX-API-Quick-Reference.md` |
| `docs/features/route-modify/spec.md` | `docs/features/route-modify/spec.md` |
| `docs/features/route-modify/implementation.md` | `docs/features/route-modify/implementation.md` |
| `docs/manual/*.py` | `docs/manual/*.py` (Python examples) |

### Data & Archive

| Old Path | New Path |
|----------|----------|
| `data/emsx_field_metadata.csv` | `data/emsx_field_metadata.csv` |
| `data/get_all_field_metadata.py` | `data/get_all_field_metadata.py` |
| `archive/*` | `archive/*` |

## New Files Added

| New Path | Purpose |
|----------|---------|
| `MarketView/README.md` | Pre-trade module documentation |
| `Execution/README.md` | Execution module documentation |
| `CostView/README.md` | Post-trade module documentation |
| `MIGRATION.md` | This migration guide |
| `config/` | Shared configuration directory |
| `tests/` | Test suites directory |

## Files Removed

The following empty/placeholder files have been removed:
- `emsx-backend/frontend/.gitkeep` (consolidated to Execution/frontend)
- `emsx-backend/logs/.gitkeep` (consolidated to Execution/backend/logs)

## Import Path Updates Required

### Frontend (Vite Config)

Update `Execution/frontend/vite.config.ts` proxy configuration if needed:

```typescript
// Before
server: {
  proxy: {
    '/api': 'http://localhost:3000',
    '/ws': { target: 'ws://localhost:3000', ws: true }
  }
}

// After (no change needed - same relative paths)
```

### Backend (Docker Compose)

Update `Execution/backend/docker-compose.yml` volume mounts if needed:

```yaml
# Before
volumes:
  - ./logs:/app/logs

# After (no change needed - relative to docker-compose.yml)
```

## Verification Checklist

After migration, verify:

- [ ] Frontend builds successfully: `cd Execution/frontend && npm run build`
- [ ] Backend starts in Docker: `cd Execution/backend && docker compose up -d`
- [ ] All scripts run correctly from new locations
- [ ] Documentation links work
- [ ] No broken imports or references

## Rollback Plan

If issues are encountered, the original structure can be restored by:

1. Reverting the git commit (if committed)
2. Manually moving files back from new locations to old locations
3. Restoring original README.md

---

*Migration completed: March 23, 2026*
