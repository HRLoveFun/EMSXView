# Error Resolution Workflow Reference

## Decision Tree

```
Error Detected
├── Search knowledge base for matching signature
│   ├── Match found
│   │   ├── Resolution still applies? → Apply it → Validate → Done
│   │   └── Resolution outdated? → Analyze context → Generate new fix → Validate → Update KB
│   └── No match
│       ├── First occurrence? → Fix it → Note it (don't add to KB yet)
│       └── Recurring (2+ times)?
│           ├── Analyze context → Generate fix → Validate
│           ├── Success → Add pattern to KB → Log iteration
│           └── Failure → Try alternative (max 3 attempts) → Log failure
```

## Pattern Entry Template

```markdown
## Pattern: {Descriptive Name}

- **Signature**: {Error message, exception type, conditions}
- **Root Cause**: {Why it happens — specific code path or configuration}
- **Resolution**:
  1. {Step 1 with file reference}
  2. {Step 2}
  ...
- **Failed Approaches** (if any):
  - {Approach that didn't work and why}
- **Status**: Resolved | Active | Investigating
- **Date**: {YYYY-MM-DD}
- **Files**: {Comma-separated file paths}
- **Lessons**: {What to watch for to prevent recurrence}
```

## EMSX-Specific Error Categories

### Bloomberg Connection Errors
- Session timeout → Check Bloomberg Terminal is running, port 8194 accessible
- Subscription failure → Verify field names in ORDER_FIELDS/ROUTE_FIELDS
- Request timeout → Check `_request_session` isolation from subscription session

### Data Parsing Errors
- Pydantic ValidationError → Field type mismatch (str vs int vs float vs None)
- Empty field → Bloomberg returns "" for unsubscribed or unavailable fields
- Silent failure → `_msg_safe_*` methods return default on error; check log for warnings

### Frontend-Backend Sync Errors
- TypeScript type error → Frontend interface doesn't match backend model
- Missing column data → Backend model has field but frontend doesn't display it
- WebSocket disconnect → Check CORS, proxy config in vite.config.ts

## Rollback Protocol

If the fix causes new failures:
1. Revert all changes immediately (git checkout or manual undo)
2. Log the failure in `iteration-log.md` with: what was tried, what broke, diagnostic data
3. Record the approach in the pattern's "Failed Approaches" section
4. Propose an alternative with justification for why it avoids the same failure
