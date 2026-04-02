# User Needs Knowledge Base

> Auto-maintained by the iterative update mechanism. Tracks recurring user needs, their priority, and automation status.

---

## Need: EMSX Field Additions

- **Frequency**: High (recurring across multiple sessions)
- **Impact**: High — each new field requires changes across 3-5 files (backend model, parsing, subscription, frontend types, UI columns)
- **Effort**: Medium per field, but repetitive
- **Current Solution**: Manual multi-file edits following the pattern in docs/CLAUDE.md
- **Proposed Automation**: A skill/prompt that takes a Bloomberg field name and type, then generates all required changes (subscription, parsing, model, TypeScript interface, UI column) as a coordinated plan
- **Status**: Identified
- **Date**: 2026-04-02

---

## Need: Bloomberg Session Management

- **Frequency**: Medium (encountered during connection issues, restarts)
- **Impact**: High — incorrect session handling blocks all operations
- **Effort**: High (complex async + threading model)
- **Current Solution**: Manual debugging with `.codebuddy/skills/emsx-api-test-integrator/` skill
- **Proposed Automation**: Extend error-resolver to detect session failures and propose targeted fixes based on session type (subscription vs request/response vs market data)
- **Status**: Identified
- **Date**: 2026-04-02

---

## Need: Backend Restart After Code Changes

- **Frequency**: High (every code change requires restart)
- **Impact**: Medium — causes confusion when changes don't take effect
- **Effort**: Low
- **Current Solution**: Manual reminder in docs; developer must remember to restart
- **Proposed Automation**: A hook or instruction that reminds to restart backend after Python file edits in `Execution/backend/`
- **Status**: Identified
- **Date**: 2026-04-02
