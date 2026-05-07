---
description: "Use when decomposing tasks, creating implementation plans, defining checkpoints, or managing multi-step workflows with validation gates."
---
# Task Planning Guidelines

## Task Decomposition

When receiving a new task:
1. **Parse requirements**: What is the expected outcome? What are the constraints?
2. **Check delivery context**: If the task is part of the execution-platform roadmap, read `docs/roadmap/wbs.md` and `.workbuddy/plans/execution-platform-status.yaml` first.
3. **Identify affected files**: Which modules, files, and functions need changes?
4. **Decompose into sub-tasks**: Each sub-task should be independently verifiable and produce a working state.
5. **Order by dependencies**: If sub-task B depends on sub-task A's output, A must come first.
6. **Estimate effort**: Reference similar past tasks in `.github/knowledge/iteration-log.md` for calibration.
7. **Assign sprint metadata**: Use phase/sprint/issue IDs whenever the work belongs to the execution-platform program.

## Checkpoint Definition

After each sub-task, verify:
- [ ] Code compiles / no syntax errors
- [ ] Linting passes (no new warnings)
- [ ] Unit tests pass for affected modules
- [ ] Integration tests pass (if applicable)
- [ ] No regressions in unrelated tests
- [ ] Performance thresholds met (if applicable)
- [ ] Security/static analysis clean (if applicable)
- [ ] Workflow artifacts updated (WBS/ledger/risk register if scope changed)

## Implementation Plan Format

```
## Task: {description}
### Sub-task 1: {name}
- Files: {list of files to modify/create}
- Changes: {brief description of changes}
- Checkpoint: {what to verify}
- Depends on: {none or previous sub-task}
- Sprint Key: {optional phase/sprint/issue ID}

### Sub-task 2: {name}
...
```

## Dynamic Adjustment

If a checkpoint fails:
1. **Stop** â€” do not proceed to the next sub-task
2. **Diagnose** â€” identify what failed and why
3. **Add corrective sub-task** â€” insert a fix step before continuing
4. **Re-validate** â€” re-run the failed checkpoint after the fix
5. **Update plan** â€” adjust remaining sub-tasks if the fix changed assumptions
6. **Log** â€” record the failure and adjustment in `.github/knowledge/iteration-log.md`
7. **Update risk state** â€” if the failure introduces a recurring blocker, update `.workbuddy/plans/execution-platform-risk-register.yaml`

## EMSX-Specific Patterns

- Backend changes require restart â€” include "restart backend" as a sub-task after Python edits
- Bloomberg field additions require coordinated changes across 3-5 files â€” decompose as: subscription â†’ backend model â†’ parser â†’ frontend type â†’ UI column
- Frontend type changes must match backend model â€” verify `types/index.ts` after backend model changes
- Structural refactors must update `.github/knowledge/architecture-decisions.md`
- Execution-platform sprint work should refresh managed status sections via `scripts/workflow/sync_execution_status.py`

