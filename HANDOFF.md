# Session Handoff Log

> Track blockers, decisions, and next steps across Claude sessions.
> Update at end of each session. Keep entries concise.

---

## Current Session (2026-03-17)

### Status
✅ Fixed Bloomberg session-sharing race condition, order status mapping, and broker algorithm refresh

### Recent Blockers (Resolved)
| Date | Issue | Resolution |
|------|-------|------------|
| 2026-03-17 | Bloomberg session sharing — request/response endpoints all timeout (30s+) | Created dedicated `_request_session` for all request/response operations ([ERR-009]) |
| 2026-03-17 | EMSX_STATUS "SENT"/"A-SENT" unmapped → orders show as "NEW" | Extended STATUS_MAP with SENT, A-SENT, ROUTED, ACTIVE, PENDING, PEND-NEW ([ERR-010]) |
| 2026-03-17 | Broker algorithms refresh produces empty configs | Fixed exchange_map to use actual Bloomberg IDs (EQ-GS, EQ-CITI, etc.) + removed strategy_configs guard |
| 2026-03-17 | `useBrokerAlgorithms` hook `isLoading` permanently stuck | Added `isLoading: false` to `refreshData` catch block ([ERR-008]) |
| 2026-03-17 | Broker-algorithms refresh blocks entire backend | Wrapped `_send_request()` with `run_in_executor` → `_send_request_async()` ([ERR-007]) |
| 2026-03-17 | Route Order Panel dropdowns unresponsive | Added on-demand strategy fetching via `cachedApiService` + fallback broker list |
| 2026-02-24 | EMSX_CURRENCY field invalid | Removed from subscription; GUIDE field mismatch identified |
| 2026-02-24 | EMSX API not enabled in EMSS | Fallback service failed; requires Bloomberg terminal config |

### Open Blockers
| Priority | Issue | Context | Next Step |
|----------|-------|---------|-----------|
| 🔴 High | Bloomberg EMSX API disabled | `Error: Not enabled for EMSX API in EMSS` | Contact IT to enable EMSX API on terminal |
| 🟡 Med | Field validation needed | EMSX_CURRENCY invalid per logs | Cross-reference GUIDE for correct field names |

### Next Tasks (Prioritized)
1. **Enable EMSX API** — Coordinate with IT department for terminal configuration
2. **Field audit** — Validate all subscription fields against GUIDE Section 5.2
3. **Route automation** — Implement `http://bstapp:50036/Trading/AutoRoute` integration
4. **Testing framework** — Add pytest for order validation logic

### In Progress
- None

### Decisions Made This Session
- Bloomberg Session 隔离架构：`self.session`（订阅）、`self._request_session`（请求）、`self._mktdata_session`（市场数据）— 三个独立 session 防止 `nextEvent()` 竞争
- `_send_request_async()` via `run_in_executor` adopted as standard pattern for all Bloomberg API calls in async handlers
- On-demand strategy fetching pattern adopted: hook provides cached data, dialog falls back to direct API call
- Three-tier loading maintained: localStorage → backend stored JSON → live Bloomberg refresh
- STATUS_MAP 扩展包含 SENT/A-SENT/ROUTED/ACTIVE/PENDING/PEND-NEW，前端同步添加 SENT badge

---

## Session History

### 2026-03-17 — Session Sharing Fix + Status Mapping + Broker Algorithm Refresh
- Fixed Bloomberg session sharing race condition: dedicated `_request_session` for all request/response (ERR-009)
- Fixed EMSX_STATUS mapping: SENT, A-SENT, ROUTED, ACTIVE now correctly mapped (ERR-010)
- Fixed broker algorithm refresh: updated exchange_map, removed strategy_configs guard → 95 configs (was 0)
- Fixed SettingsBoard tree data to reset when configs empty
- Files modified: `main.py`, `types/index.ts`, `OrderTable.tsx`, `MonitorBoard.tsx`, `SettingsBoard.tsx`

### 2026-03-17 — Critical Bug Fixes (UI + Backend Async)
- Fixed `useBrokerAlgorithms` hook `isLoading` never resetting on error (ERR-008)
- Fixed Route Order Panel with on-demand strategy fetching + broker fallback
- Fixed backend event loop blocking by wrapping all `_send_request()` calls with `run_in_executor` (ERR-007)
- Files modified: `use-broker-algorithms.ts`, `order-route-dialog.tsx`, `main.py`

### 2026-03-16 — Configuration Audit
- Created backend FastAPI with Bloomberg blpapi integration
- Built React frontend with shadcn/ui components
- Identified EMSX API connectivity issues
- Documented field metadata in `emsx_field_metadata.csv`

### Earlier Sessions
- Project initialization
- EMSX API Guide documentation conversion

---

## Quick Reference

**Backend**: `http://localhost:3000`
**Frontend**: `http://localhost:5173`
**Health Check**: `GET http://localhost:3000/api/health`
**Logs**: `logs/emsx_api.log`

**Internal Tools**:
- AutoRoute: `http://bstapp:50036/Trading/AutoRoute`
