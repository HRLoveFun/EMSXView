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
