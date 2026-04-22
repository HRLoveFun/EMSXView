# Error Patterns Knowledge Base

> Auto-maintained by the iterative update mechanism. Each pattern includes signature, root cause, resolution, and status.

---

## Pattern: EMSX Exchange Field Parsing Failure

- **Signature**: `ValidationError` on `exchange: str` field; `_orders` cache empty; all orders silently fail parsing
- **Root Cause**: `exchange = self._msg_safe_str(msg, "EMSX_EXCHANGE") or None` — Bloomberg returns empty string for EMSX_EXCHANGE; `"" or None` evaluates to `None`; Pydantic v2 rejects `None` for `exchange: str = ""`
- **Resolution**:
  1. Removed `or None` from exchange parsing
  2. Fixed route enrichment (falsy check, immediate enrichment, broadened empty-field check)
  3. Added `_derive_exchange()` to extract exchange from ticker suffix (e.g., "7203 JP Equity" → "JP")
  4. Added exchange derivation fallback in `get_orders()` and `get_routes()` enrichment
  5. Added WARNING-level diagnostic logging for INIT_PAINT complete and parse failures
- **Status**: Resolved
- **Date**: 2026-03-16
- **Files**: `Execution/backend/api/main.py`
- **Lessons**: Always handle empty-string returns from Bloomberg API; never coerce empty string to None for Pydantic str fields; backend needs restart after code changes

---

## Pattern: Strategy Parameter Type Mismatch

- **Signature**: Strategy start/end times display as empty; `EMSX_STRATEGY_START_TIME` / `EMSX_STRATEGY_END_TIME` silently return ""
- **Root Cause**: Strategy time fields are integers (HHMM format) but were parsed with `_msg_safe_str` which silently returned "" for int fields. Also: fields not in ORDER_FIELDS subscription → Bloomberg never sends them.
- **Resolution**:
  1. Added `EMSX_STRATEGY_STYLE`, `EMSX_STRATEGY_START_TIME`, `EMSX_STRATEGY_END_TIME` to ORDER_FIELDS subscription
  2. Added `strategyStyle`, `strategyStartTime`, `strategyEndTime` to backend Order model
  3. Changed parsing to `_msg_safe_int` + `_format_strategy_time()` for time fields
  4. Added missing fields to frontend Route TypeScript interface
  5. Added dedicated Strategy column in OrderTable/MonitorBoard
- **Status**: Resolved
- **Date**: 2026-03-23
- **Files**: `Execution/backend/api/main.py`, `Execution/frontend/src/types/index.ts`, `Execution/frontend/src/sections/OrderTable.tsx`, `Execution/frontend/src/sections/RouteTable.tsx`, `Execution/frontend/src/sections/MonitorBoard.tsx`
- **Lessons**: Bloomberg EMSX fields have specific types (str vs int vs float) — always match parser to field type; fields must be in subscription list or they won't be received; frontend interfaces must mirror backend model changes

---

## Pattern: launch-emsx.vbs False Startup Failure

- **Signature**: `scripts/deploy/launch-emsx.vbs` 启动后端和前端后仍返回失败或超时；服务实际已在 `3000/5173` 正常监听，但 VBS 误判为未就绪
- **Root Cause**: `IsPortOpen()` 使用 `MSXML2.XMLHTTP.6.0` 调用 `setTimeouts()`，该 COM 对象不支持该成员，导致端口探测始终走错误分支并返回 False
- **Resolution**:
  1. 将 `scripts/deploy/launch-emsx.vbs` 中的 HTTP 探测对象从 `MSXML2.XMLHTTP.6.0` 改为 `MSXML2.ServerXMLHTTP.6.0`
  2. 在对象创建失败和发送失败分支中显式 `Err.Clear`，避免错误状态污染后续判断
  3. 修正错误页中的停止指引：从不存在的 `scripts\\deploy\\stop-all.ps1` 改为真实存在的 `scripts\\stop-all.bat`
  4. 端到端验证：先释放 `3000/5173`，再执行 `cscript //nologo scripts\\deploy\\launch-emsx.vbs`，确认返回码为 `0`，并且 `http://localhost:5173` 返回 `200`
- **Status**: Resolved
- **Date**: 2026-04-21
- **Files**: `scripts/deploy/launch-emsx.vbs`
- **Lessons**: Windows Script Host 下不同 MSXML COM 类的能力不同；需要超时控制时优先使用 `ServerXMLHTTP`；启动器失败时必须区分“服务没起来”和“探活脚本误判”两类故障


---

## Pattern: CostView update status appears stuck at Started

- **Signature**: CostView Overview shows 'Started ... polling' for a long-running pipeline update; frontend status text does not surface stage/activity detail and overall progress can be miscomputed when backend stage ordering is compared lexicographically
- **Root Cause**: The frontend collapsed both 'started' and 'running' into the same generic polling copy, while the backend progress helper compared stage names lexicographically instead of by declared pipeline order. Without a last-activity timestamp, users could not distinguish a healthy long-running job from a stalled one.
- **Resolution**:
1. Extend `Execution/backend/api/routers/costview.py` job snapshots and `UpdateStatusResponse` with `last_activity_at`.
2. Update `_compute_progress()` to use `_PIPELINE_STAGES` order rather than string comparison.
3. Touch `last_activity_at` on every parsed and non-empty subprocess output line.
4. Update `Execution/frontend/src/modules/costview/types.ts` and `components/OverviewView.tsx` to show stage/progress, running vs queued copy, and stale-activity messaging.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: Execution/backend/api/routers/costview.py, Execution/frontend/src/modules/costview/types.ts, Execution/frontend/src/modules/costview/components/OverviewView.tsx, Execution/frontend/src/modules/costview/CostViewModule.tsx
- **Lessons**: For long-running background jobs, always return both coarse status and freshness/progress metadata. Avoid deriving ordered progress from string comparison when an explicit stage list already exists.


---

## Pattern: CostView aggregate stage database is locked under parallel writes

- **Signature**: `src.pipeline` Stage 3 logs `Error aggregating date <YYYYMMDD>: database is locked` during `AggregateFillsStage` while multiple date workers write `agg_fills_10s` and `processing_log` into `processed_fills.db` concurrently
- **Root Cause**: SQLite WAL mode still permits only one writer at a time. `AggregateFillsStage` used per-thread database connections but let multiple workers upsert large aggregation batches and processing-log rows concurrently, without a busy timeout or a serialized write section.
- **Resolution**:
1. Add `SQLITE_CONNECT_TIMEOUT_SEC` and `SQLITE_BUSY_TIMEOUT_MS` in `CostView/src/processing_config.py`.
2. Apply the timeout and `PRAGMA busy_timeout` in `CostView/src/processed_fills_db.py` connections.
3. Let `upsert_agg_fills_10s()` and `update_ticker_repository()` accept an optional shared connection so one aggregate transaction can cover agg rows, ticker repository updates, and `mark_date_processed()`.
4. In `CostView/src/pipeline.py`, keep per-date read/compute parallelism but serialize the Stage 3 write section with a lock and a single transaction per date.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: CostView/src/processing_config.py, CostView/src/processed_fills_db.py, CostView/src/pipeline.py, CostView/test_pipeline_guards.py
- **Lessons**: Per-thread SQLite connections are not enough for write-heavy parallel stages. When multiple workers target the same database, either serialize writes explicitly or collapse the write section into one guarded transaction with a non-zero busy timeout.


---

## Pattern: BDIB near-real-time query warnings during morning pipeline runs

- **Signature**: `xbbg.core.pipeline` emits repeated `Query date YYYY-MM-DD is too close to current time, skipping download to avoid incomplete data` warnings when CostView Stage 5 requests the latest prior trading day too early
- **Root Cause**: The BDIB incremental window treated the previous weekday as immediately eligible, even during morning/manual runs before Bloomberg intraday history for that date was considered stable. The fetch layer also lacked a final guard, so thousands of ticker-date requests could still be attempted for an unsafe date.
- **Resolution**:
1. Add `BDIB_LATEST_READY_HOUR_LOCAL` to `CostView/src/processing_config.py`.
2. In `CostView/src/pipeline.py`, compute a latest safe BDIB date and filter candidate dates above that cutoff before Stage 5 fetches start.
3. In `CostView/src/bdib_fetcher.py`, add a second-line `_is_safe_bdib_query_date()` guard so direct callers also skip unsafe recent dates.
4. Validate with targeted tests that 2026-04-21 is rejected at 2026-04-22 09:26 but accepted after the configured evening cutoff.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: CostView/src/processing_config.py, CostView/src/pipeline.py, CostView/src/bdib_fetcher.py, CostView/test_pipeline_guards.py
- **Lessons**: A valid trading day is not always a safe BDIB query day. The pipeline needs an explicit freshness cutoff, and the fetch layer should enforce it defensively to prevent warning storms.


---

## Pattern: CostView BDIB stale ticker exchange-info failure

- **Signature**: `src.bdib_fetcher` logs `BDIB fetch failed for <ticker> on <date>: 'Cannot find exchange info for <ticker>'` followed by `All 3 retries exhausted ...` across repeated Stage 5/backfill runs for the same equity ticker
- **Root Cause**: Some Bloomberg equity tickers in `ticker_repository` are stale or otherwise no longer resolvable by xbbg BDIB exchange discovery. Because the failure is deterministic, retrying the same ticker-date pair wastes Stage 5 fetch slots and Stage 6 continues to publish the bad ticker downstream.
- **Resolution**:
1. Add a dedicated tombstone file `CostView/data/outdated_tickers.json` via `CostView/src/outdated_tickers.py`.
2. In `CostView/src/bdib_fetcher.py`, detect `Cannot find exchange info` as a deterministic failure, record the ticker in the tombstone file, and stop retrying that ticker.
3. In `CostView/src/bdib_fetcher.py`, pre-filter tombstoned tickers before scheduling Stage 5 BDIB fetch pairs.
4. In `CostView/src/downstream_interface.py`, filter tombstoned equity tickers out of Stage 6 manifest/helper outputs so downstream market fetch consumers do not keep retrying them.
5. Validate with `python -m unittest CostView.test_pipeline_guards`.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: CostView/src/outdated_tickers.py, CostView/src/bdib_fetcher.py, CostView/src/downstream_interface.py, CostView/src/processing_config.py, CostView/test_pipeline_guards.py
- **Lessons**: Deterministic Bloomberg ticker-resolution failures should become persistent skip state, not transient retries. Keep the skip list in a dedicated file so Stage 5 fetch scheduling and Stage 6 manifest publication share the same source of truth.


---

## Pattern: CostView TCA order aggregation fails on None route metrics

- **Signature**: `routers.costview` logs `TCA analysis failed: unsupported operand type(s) for +: 'int' and 'NoneType'` with stack trace pointing to `CostView/src/tca_query_service.py` `_assemble_report` while averaging `cum_fill_vwap`/`cum_vwap`/`cum_tracking_error`/`cum_volume_pct` across routes
- **Root Cause**: The order-level summary builder averaged route metrics with raw `sum(...) / len(...)` logic. Some route metric dictionaries can contain `None` for one or more summary fields, so Python attempts `0 + None` and raises a TypeError instead of skipping missing metrics.
- **Resolution**:
1. Add a helper in `CostView/src/tca_query_service.py` that computes the mean of numeric values while ignoring `None` and `NaN`.
2. Replace the direct `sum(...) / len(...)` aggregations in `_assemble_report()` with that helper for `cum_fill_vwap`, `cum_vwap`, `cum_tracking_error`, and `cum_volume_pct`.
3. Add regression coverage in `CostView/test_pipeline_guards.py` for the numeric-mean helper.
4. Validate by running `python -m unittest CostView.test_pipeline_guards` and calling `POST /api/tca/analyze`.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: CostView/src/tca_query_service.py, CostView/test_pipeline_guards.py
- **Lessons**: Cross-route order summaries must treat missing route metrics as missing data, not as arithmetic inputs. Any averaging layer over partially populated TCA metrics should explicitly filter `None`/`NaN` before aggregation.
