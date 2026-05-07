# User Needs Knowledge Base

> Auto-maintained by the iterative update mechanism. Tracks recurring user needs, their priority, and automation status.

---

## Need: EMSX Field Additions

- **Frequency**: High (recurring across multiple sessions)
- **Impact**: High â€” each new field requires changes across 3-5 files (backend model, parsing, subscription, frontend types, UI columns)
- **Effort**: Medium per field, but repetitive
- **Current Solution**: Manual multi-file edits following the pattern in docs/dev-guide.md
- **Proposed Automation**: A skill/prompt that takes a Bloomberg field name and type, then generates all required changes (subscription, parsing, model, TypeScript interface, UI column) as a coordinated plan
- **Status**: Identified
- **Date**: 2026-04-02

---

## Need: Bloomberg Session Management

- **Frequency**: Medium (encountered during connection issues, restarts)
- **Impact**: High â€” incorrect session handling blocks all operations
- **Effort**: High (complex async + threading model)
- **Current Solution**: Manual debugging with `.codebuddy/skills/emsx-api-test-integrator/` skill
- **Proposed Automation**: Extend error-resolver to detect session failures and propose targeted fixes based on session type (subscription vs request/response vs market data)
- **Status**: Identified
- **Date**: 2026-04-02

---

## Need: Backend Restart After Code Changes

- **Frequency**: High (every code change requires restart)
- **Impact**: Medium â€” causes confusion when changes don't take effect
- **Effort**: Low
- **Current Solution**: Manual reminder in docs; developer must remember to restart
- **Proposed Automation**: A hook or instruction that reminds to restart backend after Python file edits in `ExecutionView/backend/`
- **Status**: Identified
- **Date**: 2026-04-02


---

## Need: Backend runtime warning triage

- **Frequency**: Medium
- **Impact**: High
- **Effort**: TBD
- **Current Solution**: Manual backend restart, log inspection, targeted code patching, and ad hoc smoke tests after warnings appear in startup/runtime logs.
- **Proposed Automation**: Add startup/runtime regression guards for optional dependencies and known Bloomberg log signatures, plus focused tests that validate health endpoint semantics and refdata warning classification.
- **Status**: Identified
- **Date**: 2026-04-22


---

## Need: Architecture documentation alignment

- **Frequency**: Medium
- **Impact**: High
- **Effort**: TBD
- **Current Solution**: Manual review of docs against live code structure, then ad hoc rewrites and archival when old paths or obsolete module boundaries are discovered.
- **Proposed Automation**: Maintain a docs root index plus archive policy, add lightweight checks for stale path patterns like app/ and emsx-backend/ in active docs, and require core docs updates when architecture-facing files or entrypoints change.
- **Status**: Identified
- **Date**: 2026-04-22


---

## Need: EMSX route contract hardening and asset-class-aware strategy discovery

- **Frequency**: Medium
- **Impact**: High
- **Effort**: TBD
- **Current Solution**: Manual code archaeology against Bloomberg EMSX docs, followed by targeted backend/frontend fixes and ad hoc validation for RouteEx, ModifyRouteEx, broker strategy lookup, and session behavior.
- **Proposed Automation**: Maintain a dedicated EMSX routing regression suite that validates RouteEx/ModifyRouteEx request construction, reset sentinels, strategy payload forwarding, asset-class discovery, and request-session correlation handling before release.
- **Status**: Identified
- **Date**: 2026-04-23


---

## Need: Layered startup status and early-visible frontend startup UX

- **Frequency**: Medium
- **Impact**: High
- **Effort**: TBD
- **Current Solution**: Manual launcher debugging, backend/ frontend code archaeology, ad hoc startup gates, and repeated live checks to distinguish HTTP readiness, Bloomberg connection, and subscription warmup.
- **Proposed Automation**: Maintain a first-class startup-status contract with explicit phases, reuse a shared frontend startup hook/status surface, and keep launcher/frontend validation tests that assert early frontend visibility plus backend warmup transitions.
- **Status**: Identified
- **Date**: 2026-04-23


---

## Need: Layered startup visibility and service orchestration

- **Frequency**: Very High
- **Impact**: High
- **Effort**: TBD
- **Current Solution**: Launcher, service-manager, frontend startup gate, and diagnose scripts now share `/api/startup-status`, but operators still validate some transitions manually and compare multiple surfaces during start/restart flows.
- **Proposed Automation**: Continue consolidating launcher, service-manager, and frontend startup surfaces around one phased readiness contract, reusable startup summaries, and machine-readable status outputs for orchestration and regression checks.
- **Status**: Identified
- **Date**: 2026-04-23


---

## Need: CostView Attribution æ¨¡å—ä¸Žæ•°æ®å±‚è§£è€¦

- **Frequency**: 2
- **Impact**: 5
- **Effort**: TBD
- **Current Solution**: attribution æ¨¡å—ä¸šåŠ¡é€»è¾‘ï¼ˆwriter/aggregator/recommender/configï¼‰ç›´æŽ¥åµŒå…¥ SQL æŸ¥è¯¢ã€ç¡¬ç¼–ç  DB è·¯å¾„ã€ç´§è€¦åˆ sqlite3.Connectionï¼Œæ— æ³•ç‹¬ç«‹æµ‹è¯•
- **Proposed Automation**: å·²å®Œæˆï¼šå¼•å…¥ Protocol æŽ¥å£æŠ½è±¡å±‚ + DTO æ•°æ®ç±» + Repository å®žçŽ° + ä¾èµ–æ³¨å…¥ï¼Œä¸šåŠ¡é€»è¾‘ä¸Žæ•°æ®è®¿é—®å®Œå…¨åˆ†ç¦»
- **Status**: Identified
- **Date**: 2026-05-07

