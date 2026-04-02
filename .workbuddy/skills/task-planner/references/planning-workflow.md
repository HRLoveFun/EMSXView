# Task Planning Workflow Reference

## Plan Template

```markdown
# Task: {Title}
**Requested**: {Date}
**Estimated Sub-tasks**: {N}
**Estimated Effort**: {Small/Medium/Large}

## Pre-conditions
- {What must be true before starting}

## Sub-tasks

### 1. {Sub-task Name}
- **Files**: {files to modify/create}
- **Changes**: {what to do}
- **Depends on**: None
- **Checkpoint**:
  - [ ] Linting passes
  - [ ] Tests pass: {specific test commands}
  - [ ] {Additional verification}

### 2. {Sub-task Name}
- **Files**: {files}
- **Changes**: {description}
- **Depends on**: Sub-task 1
- **Checkpoint**:
  - [ ] Tests pass: {commands}
  - [ ] {Verification}

... (repeat for each sub-task)

## Post-conditions
- {What must be true when done}
- [ ] All tests pass
- [ ] No regressions
- [ ] Iteration log updated
```

## Checkpoint Criteria by Type

### Code Change Checkpoint
- [ ] No syntax errors
- [ ] Linting clean
- [ ] Unit tests for changed module pass
- [ ] No new type errors (TypeScript) or validation errors (Pydantic)

### Bloomberg Integration Checkpoint
- [ ] Field in subscription list
- [ ] Parser matches field type
- [ ] Backend model includes field
- [ ] Frontend type interface updated
- [ ] UI renders field correctly

### UI Change Checkpoint
- [ ] Component renders without errors
- [ ] Data displays correctly (mock or live)
- [ ] No layout regressions in related components
- [ ] Responsive behavior preserved

### Backend API Checkpoint
- [ ] Endpoint returns expected response shape
- [ ] Error cases return proper HTTP status codes
- [ ] Health check still passes
- [ ] WebSocket connections still work

## Dynamic Replanning Rules

When a checkpoint fails:

1. **Diagnose**: What exactly failed? (test name, error message, expected vs actual)
2. **Classify**:
   - **Trivial fix** (typo, missing import) → fix inline, re-run checkpoint
   - **Design issue** (wrong approach) → add corrective sub-task before next sub-task
   - **Blocker** (external dependency, Bloomberg API issue) → pause plan, document blocker, propose workaround
3. **Insert corrective sub-task** with its own checkpoint
4. **Re-evaluate remaining sub-tasks**: Do any need adjustment based on the fix?
5. **Log the revision** in the plan and in `iteration-log.md`

## EMSX-Specific Patterns

### Adding a Bloomberg Field (5 sub-tasks)
1. Backend: Add to ORDER_FIELDS/ROUTE_FIELDS subscription list
2. Backend: Add to Order/Route model with correct type
3. Backend: Add parsing with correct `_msg_safe_*` method
4. Frontend: Update TypeScript interface in types/index.ts
5. Frontend: Add UI column in relevant table component

### Modifying Order Behavior (3+ sub-tasks)
1. Backend: Update route handler / business logic
2. Backend: Update tests
3. Frontend: Update API call and UI state management
4. (Optional) Frontend: Update display components
