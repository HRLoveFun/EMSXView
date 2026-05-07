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
- **Files**: `ExecutionView/backend/api/main.py`
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
- **Files**: `ExecutionView/backend/api/main.py`, `ExecutionView/frontend/src/types/index.ts`, `ExecutionView/frontend/src/sections/OrderTable.tsx`, `ExecutionView/frontend/src/sections/RouteTable.tsx`, `ExecutionView/frontend/src/sections/MonitorBoard.tsx`
- **Lessons**: Bloomberg EMSX fields have specific types (str vs int vs float) — always match parser to field type; fields must be in subscription list or they won't be received; frontend interfaces must mirror backend model changes

---

## Pattern: ModifyRouteEx rejects strategy change with "Invalid Strategy Parameter"

- **Signature**: 前端 Trade 视图 "Change strategy" 中修改单个字段（如 Max % Vol = 8）提交时，弹出 `Invalid Strategy Parameter`，后端日志显示 Bloomberg 对 `ModifyRouteEx`（或 `RouteEx`）返回错误
- **Root Cause**: `_apply_strategy_params` 会逐个将 `strategyParams.fields` 追加为 `EMSX_STRATEGY_FIELDS` + `EMSX_STRATEGY_FIELD_INDICATORS`；当字段 `disabled=false` 但 `value=""`（或 `None`）时，会发出 `EMSX_FIELD_INDICATOR=0` 搭配空 `EMSX_FIELD_DATA`。Bloomberg EMSX 要求 indicator=0 时必须带有非空数据，否则整个策略请求以 "Invalid Strategy Parameter" 拒绝。前端会把用户未显式修改过、但 Bloomberg 返回 `Disable=0` 的字段（`disabled=false`, `value=""`）一并回传，导致一次单字段修改失败。
- **Resolution**:
  1. 在 `ExecutionView/backend/api/services/bloomberg_adapter.py::_apply_strategy_params` 中，把 `None` 规范化为空串并 `strip()`；若 `disabled=false` 且值为空，自动降级为 `indicator=1`（跳过）+ 空数据，避免向 Bloomberg 发送非法组合。
  2. 新增回归测试 `test_modify_route_treats_empty_strategy_fields_as_skipped`（`ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py`），覆盖空串/None/显式 disabled 场景。
- **Status**: Resolved
- **Date**: 2026-04-24
- **Files**: `ExecutionView/backend/api/services/bloomberg_adapter.py`, `ExecutionView/backend/api/tests/test_bloomberg_adapter_routing.py`
- **Lessons**: Bloomberg EMSX 的 `EMSX_FIELD_INDICATOR` 必须与 `EMSX_FIELD_DATA` 严格一致 —— indicator=0 要求非空值，否则整个 strategy 请求都会被拒绝；前端把全量字段回传时，后端必须在序列化层兜底过滤空启用字段，而不是依赖前端一定把空字段标记为 disabled。

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
1. Extend `ExecutionView/backend/api/routers/costview.py` job snapshots and `UpdateStatusResponse` with `last_activity_at`.
2. Update `_compute_progress()` to use `_PIPELINE_STAGES` order rather than string comparison.
3. Touch `last_activity_at` on every parsed and non-empty subprocess output line.
4. Update `ExecutionView/frontend/src/modules/costview/types.ts` and `components/OverviewView.tsx` to show stage/progress, running vs queued copy, and stale-activity messaging.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: ExecutionView/backend/api/routers/costview.py, ExecutionView/frontend/src/modules/costview/types.ts, ExecutionView/frontend/src/modules/costview/components/OverviewView.tsx, ExecutionView/frontend/src/modules/costview/CostViewModule.tsx
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


---

## Pattern: CostView Analysis local-time drift and null market metrics

- **Signature**: CostView Analysis tab shows route Time in NY time instead of local exchange time; order/route VWAP, Tracking Error, Vol % Interval, and Price Move return null for rows that should use local bar alignment; Vol % ADV20 is unrealistically large because it is computed from daily market volume instead of order filled volume.
- **Root Cause**: Two query-path issues compounded the display failure: 1) `batch_convert_ny_to_local()` returned a mixed-timezone pandas Series that was coerced back to the source timezone, so stored `exchange_exec_time` and related route windows stayed in NY time for non-US exchanges; 2) `tca_query_service.py` compared `raw_bdib.mkt_timestamp` as if it contained `date + time`, but the live DB stores time-only strings. Separately, `volume_pct_adv20` used `total_volume / adv_20d` instead of order filled volume / ADV, and the order table's `Volatility` column still bound to `intraday_volatility` rather than Stage 7 `daily_volatility`.
- **Resolution**:
1. Change `CostView/src/exchange_tz.py` `batch_convert_ny_to_local()` to return tz-naive local wall-clock datetimes so mixed exchanges preserve their local time values. 2. In `CostView/src/tca_query_service.py`, derive route `start_time`/`end_time` from `DateTimeOfFill + Exchange` instead of trusting stored `exchange_exec_time` only. 3. Compare `raw_bdib.mkt_timestamp` via `substr(mkt_timestamp, -8)` so both time-only and datetime-formatted rows work. 4. Compute `volume_pct_adv5/20` from order filled volume, not from market `total_volume`. 5. Add `daily_volatility` to the order summary and bind the Analysis order-table `Volatility` column to it while keeping `intraday_volatility` for detailed intraday views. 6. Add a raw_bdib-based fallback in `tca_query_service.py` for missing route benchmark / tracking / volume metrics when bar data exists but legacy fill_bdib rows were built with bad local-time alignment. 7. Validate with `pytest CostView/tests/test_tca_query_service.py CostView/test_pipeline_guards.py` and `npm run build` in `ExecutionView/frontend`.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: CostView/src/exchange_tz.py, CostView/src/tca_query_service.py, ExecutionView/backend/api/routers/costview.py, ExecutionView/frontend/src/modules/costview/types.ts, ExecutionView/frontend/src/modules/costview/components/TcaOrderTable.tsx, CostView/tests/test_tca_query_service.py, CostView/test_pipeline_guards.py
- **Lessons**: When one pipeline step stores exchange-local wall-clock time for multiple markets, never keep a mixed-timezone pandas Series in a single tz-aware dtype. For SQLite market-bar tables, verify the real on-disk timestamp shape before building comparisons. In TCA, ADV-based participation must use order volume, not market volume, and UI labels must stay aligned with the agreed business semantic (`daily_volatility` vs `intraday_volatility`).


---

## Pattern: EMSX SENT status enum mismatch

- **Signature**: FastAPI backend logs 'Error parsing order message' with Pydantic enum validation for status input_value='SENT' even though Bloomberg STATUS_MAP already maps SENT/A-SENT to 'SENT'.
- **Root Cause**: ExecutionView/backend/api/services/bloomberg_adapter.py can emit status='SENT', but ExecutionView/backend/api/schemas.py OrderStatus enum omitted SENT, so Order model validation rejected otherwise valid Bloomberg updates.
- **Resolution**:
1. Add SENT = 'SENT' to ExecutionView/backend/api/schemas.py OrderStatus.
2. Keep STATUS_MAP in bloomberg_adapter.py aligned with OrderStatus values.
3. Add a regression test that OrderStatus('SENT') parses successfully.
4. Restart backend and confirm startup logs no longer show the SENT validation warning.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: ExecutionView/backend/api/schemas.py, ExecutionView/backend/api/services/bloomberg_adapter.py, ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py
- **Lessons**: When Bloomberg status normalization changes, update downstream enums in the same change; otherwise runtime warnings only appear on live order paints.


---

## Pattern: FX refdata duplicate correlation id

- **Signature**: Backend logs 'Failed to send FX refdata request: Duplicate correlation id' repeatedly after Bloomberg refdata responses.
- **Root Cause**: The mktdata event loop cleared _fx_refdata_pending and _crncy_refdata_pending on any RESPONSE event, even when the completed response belonged to a different refdata request type. That allowed a new FX sendRequest attempt while the original FX correlation id was still active.
- **Resolution**:
1. In ExecutionView/backend/api/services/bloomberg_adapter.py, collect correlation ids seen in each refdata RESPONSE event.
2. Clear pending flags only for matching request types via a helper such as _mark_refdata_response_complete().
3. Add a regression test proving a CRNCY response does not clear FX pending.
4. Restart backend and verify the duplicate correlation warning disappears from startup logs.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: ExecutionView/backend/api/services/bloomberg_adapter.py, ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py
- **Lessons**: Pending flags for Bloomberg requests must be tied to the exact correlation id or request family; global cleanup on shared sessions is unsafe.


---

## Pattern: Optional DB bootstrap hits Docker host on local startup

- **Signature**: Backend startup logs 'Database schema bootstrap failed: [Errno 11001] getaddrinfo failed' when DATABASE_URL defaults to postgresql+asyncpg://...@postgres:5432/... on a non-Docker local run.
- **Root Cause**: ExecutionView/backend/api/main.py always attempted initialize_database() during lifespan startup even when ENABLE_DB_PERSISTENCE was false. On local Windows runs, the default DATABASE_URL host 'postgres' is unresolved, so the optional persistence probe emitted a misleading startup warning.
- **Resolution**:
1. Gate schema bootstrap behind settings.ENABLE_DB_PERSISTENCE in ExecutionView/backend/api/main.py.
2. When persistence is disabled, mark the repository provider as not ready and log an INFO message that bootstrap is skipped.
3. Update /api/health to report database status as 'disabled' with message 'DB persistence disabled' instead of probing the database.
4. Keep real bootstrap failures as warnings only when persistence is enabled.
5. Validate with pytest on connection/db tests and confirm startup logs no longer show getaddrinfo warnings.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: ExecutionView/backend/api/main.py, ExecutionView/backend/api/routers/connection.py, ExecutionView/backend/api/db.py, ExecutionView/backend/api/tests/test_connection_router.py
- **Lessons**: Optional infrastructure should not be probed like a hard dependency. Health and startup semantics must agree on whether a subsystem is disabled versus disconnected.


---

## Pattern: FX scaled direct quote warning noise

- **Signature**: Backend repeatedly logs warnings like 'FX KRW: direct=... vs inverse=... (ratio=100.00x) — using inverse' or 'FX IDR: ... (ratio=999.69x) — using inverse' every FX refresh cycle.
- **Root Cause**: Some Bloomberg direct FX pairs are quoted in scaled units (for example per 100 or per 1000 local currency units). The code intentionally preferred the inverse USD{ccy} quote, but still compared the raw direct quote to the inverse quote and emitted a WARNING on every refresh even for known stable scale differences.
- **Resolution**:
1. Keep inverse quotes authoritative when both direct and inverse are present.
2. Detect power-of-ten scaling differences (10x/100x/1000x/10000x) between direct and inverse quotes in ExecutionView/backend/api/services/bloomberg_adapter.py.
3. When the scaled direct quote normalizes within the discrepancy threshold, log a one-time INFO message per currency instead of a repeated WARNING.
4. Preserve WARNING level only for non-scaled discrepancies that still exceed the threshold after normalization.
5. Add regression tests covering scaled and unscaled discrepancy handling and verify startup/runtime logs no longer show repeated KRW/IDR warnings at WARNING level.
- **Status**: Resolved
- **Date**: 2026-04-22
- **Files**: ExecutionView/backend/api/services/bloomberg_adapter.py, ExecutionView/backend/api/tests/test_bloomberg_adapter_refdata.py
- **Lessons**: Diagnostic logging should encode known market-data quote conventions; otherwise expected behavior becomes chronic warning noise that hides real issues.


---

## Pattern: pytest_asyncio autoload collection crash on local workspace

- **Signature**: Running pytest in this workspace with plugin autoload enabled crashes during collection with `AttributeError: 'Package' object has no attribute 'obj'`, triggered before normal test discovery when `pytest_asyncio` is auto-loaded.
- **Root Cause**: The local pytest environment auto-loads an incompatible `pytest_asyncio` plugin version during collection, so failures occur before repository tests run and are unrelated to the application code under test.
- **Resolution**:
1. Disable third-party pytest plugin autoload for local validation with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
2. Run pytest from the repository root when tests import `CostView` as a package.
3. Re-run the focused test command to surface real code failures.
4. If needed later, fix the environment plugin version separately instead of changing repository test code to compensate.
- **Status**: Resolved
- **Date**: 2026-04-23
- **Files**: CostView/tests/test_fill_fetch.py, CostView/tests/test_tca_query_service.py, CostView/test_pipeline_guards.py, ExecutionView/backend/api/tests/test_service_provider.py, ExecutionView/backend/api/tests/test_db_bootstrap.py
- **Lessons**: When pytest fails before collection with framework/plugin stack traces, treat the environment as the first suspect and neutralize plugin autoload before debugging application code.

---

## Pattern: raw_bdib.vwap Column Always NULL

- **Signature**: Computed `vwap_bps` is 100% NaN even though `interval_vwap` calls succeed; SELECT vwap FROM raw_bdib returns all NULL.
- **Root Cause**: Bloomberg BDIB feed populates OHLCV but not the vwap column for the tickers / dates we subscribe to. The column exists in the schema but is never written.
- **Resolution**: In `CostView/src/attribution/benchmarks.py`, ignore `raw_bdib.vwap` entirely. Compute the bar VWAP proxy manually as `sum(close * volume) / sum(volume)` over all bars in [first_minute, last_minute] (inclusive). Never SELECT vwap.
- **Status**: Resolved
- **Date**: 2026-04-28
- **Files**: `CostView/src/attribution/benchmarks.py`
- **Lessons**: Always SELECT a small sample of raw bar data before relying on a derived column. BDIB has many nullable columns; assume nothing about field population.

---

## Pattern: Sub-minute Bar Grid Loses Volume on Dedup-by-Minute

- **Signature**: interval_vwap returns prices that don''t match observed VWAP; total volume in interval is too low.
- **Root Cause**: raw_bdib bars are NOT a clean 1-minute grid. Many bars use sub-minute timestamps (e.g. 09:30:10, 09:30:20, ... 09:30:50) plus a 09:30:00 minute mark. Naive `drop_duplicates(subset=["minute"], keep="last")` discards 4 of 5 sub-minute bars and most of the volume.
- **Resolution**: Keep ALL sub-minute rows in BarPanel.bars. Only dedup by minute when computing `mid_by_minute` (we want the last close per minute as a spot mid lookup). For volume integration in `interval_vwap` and `interval_volume`, retain every bar and sum across the full sub-minute panel.
- **Status**: Resolved
- **Date**: 2026-04-28
- **Files**: `CostView/src/attribution/benchmarks.py`, `CostView/src/attribution/writer.py`
- **Lessons**: Verify the time grid of Bloomberg bar data with a quick `SELECT mkt_timestamp, COUNT(*) GROUP BY mkt_timestamp` before designing aggregations.

---

## Pattern: pytest-asyncio 9.0.2 Fails Test Collection

- **Signature**: `AttributeError: ''Package'' object has no attribute ''obj''` during pytest collection.
- **Root Cause**: pytest-asyncio 9.0.2 is incompatible with the installed pytest version; package collection hooks reference `pkg.obj` which no longer exists.
- **Resolution**: Use `python -m unittest CostView.tests.<module> -v` for CostView tests instead of pytest. All CostView tests inherit from `unittest.TestCase` so this works directly.
- **Status**: Workaround
- **Date**: 2026-04-28
- **Files**: N/A (testing tooling)
- **Lessons**: When pytest collection breaks, fall back to plain unittest before debugging plugin compatibility.


---

## Pattern: LSE (LN Equity) mktdata subscription fails with rcode=-11

- **Signature**: 日志: "Mktdata subscription failures: N ([('XX/ LN Equity', 'Invalid security, rcode = -11')])"
- **Root Cause**: Bloomberg //blp/mktdata 不接受根符号中包含 `/` 的 LSE ticker（如 "UU/ LN Equity"）。EMSX 中的 ticker 格式保留了 Bloomberg 原始格式的 `/`，但 mktdata 服务需要标准格式（如 "UU LN Equity"）。
- **Resolution**:
1. 在 _update_mktdata_subscriptions 中，对 LN Equity ticker 做根符号 `/` 剥离 (ticker.replace('/', '')) 后作为 mktdata topic；CorrelationId 保持原始 ticker 以正确映射数据。2. 在 SUBSCRIPTION_STATUS 处理中增加 errorCode 提取和日志记录。
- **Status**: Resolved
- **Date**: 2026-05-05
- **Files**: ExecutionView/backend/api/services/bloomberg_adapter.py
- **Lessons**: 不同 Bloomberg API 服务对 ticker 格式要求可能不同。EMSX API 接受 "UU/ LN Equity" 但 mktdata 可能需要 "UU LN Equity"。在跨服务使用 ticker 时需注意格式差异。


---

## Pattern: Bloomberg EMSX 拒绝 "Invalid Handling Instruction"

- **Signature**: batch_route_service - WARNING - batch-route item key={orderId}#{broker} status=FAILED rtt_ms={ms} detail=Invalid Handling Instruction
- **Root Cause**: Bloomberg EMSX 拒绝 RouteEx 请求中的 EMSX_HAND_INSTRUCTION 值。值来自 broker_hand_instruction.json 中该 broker 的配置（如 EQ-BARCLAY→AUTO1、EQ-JPM→DOT）。值本身在 pipeline 中未被篡改，但 Bloomberg/托管券商端未启用或未识别该 HAND_INSTRUCTION 类型。
- **Resolution**:
1. 确认 broker_hand_instruction.json 中该 broker 的 HAND_INSTRUCTION 配置正确。2. 检查 Bloomberg EMSX 端该 broker 账户是否启用了对应的 HAND_INSTRUCTION。3. 联系券商/Bloomberg 确认该 HAND_INSTRUCTION（如 AUTO1、DOT）是否在账户级别已激活。4. 测试替代值（如 "ANY"）确认是否是配置值本身的问题。
- **Status**: Resolved
- **Date**: 2026-05-05
- **Files**: ExecutionView/backend/api/data/broker_hand_instruction.json, ExecutionView/backend/api/services/route_service.py, ExecutionView/backend/api/services/bloomberg_adapter.py
- **Lessons**: 1. HAND_INSTRUCTION 是 broker 级别的 Bloomberg EMSX 配置，需券商端配合激活。2. 新增 broker 必须先在 broker_hand_instruction.json 中配置，再联系 Bloomberg 确认该值已被券商接受。3. "Invalid Handling Instruction" 错误 99% 是券商/Bloomberg 端问题，非代码 bug。


---

## Pattern: batch-route-black-screen-no-error-boundary

- **Signature**: 点击 batch route/modify 的 Validate 或 Submit 按钮后，整个页面变白/黑（React 组件树崩溃）
- **Root Cause**: 项目缺少 ErrorBoundary 错误边界 + 部分异步提交函数（BatchModifyDialog.runSubmit）缺少 try-catch 保护 + streamNdjsonBatch 缺少超时机制。任何未捕获异常（buildRequest 抛出、回调异常、网络错误等）都会向上传播到 React 根组件，导致整个页面空白。
- **Resolution**:
1. 创建 ErrorBoundary 组件包裹主内容区，确保局部崩溃不会导致全页面空白 2. 为 BatchModifyDialog.runSubmit 添加 try-catch（与 BatchRouteOrderDialog 保持一致） 3. 使用 ref 同步 summary 状态，解决陈旧闭包问题 4. 为 streamNdjsonBatch 添加 AbortSignal.timeout 超时保护（5分钟）
- **Status**: Resolved
- **Date**: 2026-05-06
- **Files**: ExecutionView/frontend/src/components/error-boundary.tsx, ExecutionView/frontend/src/App.tsx, ExecutionView/frontend/src/components/batch-operation-dialogs.tsx, ExecutionView/frontend/src/services/api.ts
- **Lessons**: 1. 所有 React 项目必须有 ErrorBoundary 包裹 2. 所有异步提交函数必须包裹 try-catch 3. setState 异步更新后不能立即读取状态值，应使用 ref 或 onSummary 回调 4. NDJSON 流式请求必须有超时机制
