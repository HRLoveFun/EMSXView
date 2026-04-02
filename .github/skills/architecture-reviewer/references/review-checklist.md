# Architecture Review Checklist

## Health Thresholds

| Metric | Warning | Critical | Current Status |
|--------|---------|----------|----------------|
| File size (lines) | > 500 | > 1000 | main.py: ~3695 (CRITICAL) |
| Function size (lines) | > 30 | > 50 | Needs audit |
| Module dependencies | > 5 direct | > 10 direct | Needs audit |
| Copy-paste instances | 2 | 3+ | Needs audit |
| Test coverage | < 80% | < 50% | Needs audit |

## EMSX-Specific Review Items

### Backend (`Execution/backend/api/main.py`)
- [ ] **Decomposition candidates**: Bloomberg session management, order/route models, route enrichment, broker algorithm cache, WebSocket handlers
- [ ] **Session isolation**: Are subscription, request, and market data sessions properly isolated?
- [ ] **Error boundaries**: Do Bloomberg API failures propagate cleanly to API responses?
- [ ] **Field consistency**: Do ORDER_FIELDS and ROUTE_FIELDS match what the frontend expects?
- [ ] **Audit logging**: Is ENABLE_AUDIT_LOG covering all state-changing operations?

### Frontend (`Execution/frontend/src/`)
- [ ] **Component size**: Are table sections (OrderTable, RouteTable, MonitorBoard) growing too large?
- [ ] **Type safety**: Does `types/index.ts` match all backend response fields?
- [ ] **Cache invalidation**: Does `cachedApiService` TTL cause stale data issues?
- [ ] **Strategy data**: Are local JSON files and Bloomberg API data merged correctly?
- [ ] **Error handling**: Do API failures show user-friendly messages?

### CostView (`CostView/src/`)
- [ ] **Pipeline stages**: Are the 5 stages (ingest, process, aggregate, label, BDIB) independently testable?
- [ ] **Schema evolution**: Can raw_fills.db schema change without breaking processed_fills.db?
- [ ] **Bloomberg dependency**: Can the pipeline run with cached BDIB data when Bloomberg is unavailable?

## Refactoring Patterns

### Extract Module (for main.py decomposition)
1. Identify a cohesive set of functions (e.g., all Bloomberg session management)
2. Create new module file with those functions
3. Add imports in main.py to maintain the same API surface
4. Run all tests — must pass before proceeding
5. Repeat for next extraction target

### Extract Component (for large React sections)
1. Identify a self-contained UI section (e.g., filter bar, action toolbar)
2. Extract into a new component file with typed props
3. Import in parent component
4. Verify rendering and interactivity are unchanged

### Pipeline Stage Isolation (for CostView)
1. Ensure each stage reads from DB and writes to DB (no in-memory coupling)
2. Add stage-level test with fixture data
3. Verify stage can be re-run idempotently

## Decision Template

```markdown
## Decision: {Title}

- **Date**: {YYYY-MM-DD}
- **Context**: {What prompted this decision}
- **Decision**: {What was decided}
- **Consequences**: {Positive and negative effects}
- **Technical Debt**: {LOW/MED/HIGH — any debt this creates}
- **Review Date**: {When to re-evaluate}
```
