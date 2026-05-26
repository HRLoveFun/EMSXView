# Error Patterns

Common error patterns and solutions encountered in EMSX development.

## Bloomberg EMSX Connection

### Bloomberg session startup timeout or API errors

**Pattern:** `bloomberg_adapter.py` connect() fails with timeout or API error.  
**Cause:** Bloomberg Terminal/BPIPE not running locally, or `BLOOMBERG_HOST`/`BLOOMBERG_PORT` misconfigured.  
**Solution:** Verify Bloomberg is running on the configured host. Use `VITE_USE_MOCK=true` for frontend development without Bloomberg. The Bloomber session starts asynchronously — frontend should check startup status before sending orders.

### "Time too close" BDIB fetch rejection

**Pattern:** xbbg/bdib_fetcher refuses to return data for the most recent 1-2 trading days in real-time mode.  
**Cause:** Bloomberg API protection against fetching incomplete intraday data for the current day.  
**Solution:** For incremental runs, accept that the latest day may be missing BDIB data. The pipeline's daily batch mode processes previous trading days. See `docs/handoff.md` for known workarounds.

## Data Pipeline

### Raw fills date format inconsistencies

**Pattern:** `order_as_of_date` field has inconsistent format between API sources and Excel imports.  
**Cause:** Bloomberg EMSX API returns ISO-8601 timestamps; Excel files use `%Y%m%d` format. The cleaner handles multiple formats but edge cases remain.  
**Solution:** `DataPipeline/config.py` defines `EMSX_DATETIME_FORMATS` as the canonical format list. If a new format appears, add it there.

### BDIB integration skipping tickers

**Pattern:** Some tickers are not integrated into fill_bdib despite appearing in raw_fills.  
**Cause:** Exchange code mismatch in `Config.BDIB_EXCHANGE` list. The BDIB fetcher only processes tickers whose exchange is in the allow-list.  
**Solution:** Check if the ticker's exchange is in `Config.BDIB_EXCHANGE`. Add the exchange code if needed.

## Frontend

### Module lazy-load failures

**Pattern:** A module tab shows blank content or loading spinner never resolves.  
**Cause:** The module's chunk failed to load (404) or the module component threw during mount.  
**Solution:** Check browser console for chunk load errors. Verify the module's entry point (`modules/<name>/index.tsx`) exists and exports a default React component.

### Path alias not resolving in import

**Pattern:** TypeScript/Vite cannot resolve `@execution/*` or `@costview/*` imports.  
**Cause:** Path alias defined in `tsconfig.app.json` but not in `vite.config.ts`, or vice versa. Both must be in sync.  
**Solution:** Check both files for the alias definition. `vite.config.ts` handles runtime resolution; `tsconfig.app.json` handles IDE/type checking.

## Backend API

### Optional router import failure

**Pattern:** Backend starts but CostView/DatabaseView/ExecutionHistory endpoints return 404.  
**Cause:** The optional router's import failed during `_register_optional()` in `main.py`.  
**Solution:** Check server logs for "[router] 未加载" warning messages. The core ExecutionView continues to function — this is by design for graceful degradation.

### Database schema bootstrap failure

**Pattern:** Backend starts but `ENABLE_DB_PERSISTENCE` shows `db_ready: false` in startup status.  
**Cause:** PostgreSQL not running, wrong credentials, or schema migration failed.  
**Solution:** Verify PostgreSQL is healthy (`docker compose ps postgres`). Check connection string in `.env`. Without DB persistence, the backend falls back to in-memory state.

## Testing

### Monkeypatch path errors in tests

**Pattern:** `AttributeError: has no attribute 'platform_data'` or similar in test setup.  
**Cause:** `monkeypatch.setattr` targets a module attribute that doesn't exist at the import level. Often due to lazy imports.  
**Solution:** Patch the attribute where it is *used* (e.g., in the router module), not where it is *defined*. Use `monkeypatch.setattr('routers.execution_history.execution_history_adapter', ...)` instead of patching the platform_data module directly.
