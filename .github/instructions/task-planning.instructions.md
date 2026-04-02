---
description: "Use when decomposing tasks, creating implementation plans, defining checkpoints, or managing multi-step workflows with validation gates."
---
# Task Planning Guidelines

## Task Decomposition

When receiving a new task:
1. **Parse requirements**: What is the expected outcome? What are the constraints?
2. **Identify affected files**: Which modules, files, and functions need changes?
3. **Decompose into sub-tasks**: Each sub-task should be independently verifiable and produce a working state
4. **Order by dependencies**: If sub-task B depends on sub-task A's output, A must come first
5. **Estimate effort**: Reference similar past tasks in `.github/knowledge/iteration-log.md` for calibration

## Checkpoint Definition

After each sub-task, verify:
- [ ] Code compiles / no syntax errors
- [ ] Linting passes (no new warnings)
- [ ] Unit tests pass for affected modules
- [ ] Integration tests pass (if applicable)
- [ ] No regressions in unrelated tests
- [ ] Performance thresholds met (if applicable)
- [ ] Security/static analysis clean (if applicable)

## Implementation Plan Format

```
## Task: {description}
### Sub-task 1: {name}
- Files: {list of files to modify/create}
- Changes: {brief description of changes}
- Checkpoint: {what to verify}
- Depends on: {none or previous sub-task}

### Sub-task 2: {name}
...
```

## Dynamic Adjustment

If a checkpoint fails:
1. **Stop** — do not proceed to the next sub-task
2. **Diagnose** — identify what failed and why
3. **Add corrective sub-task** — insert a fix step before continuing
4. **Re-validate** — re-run the failed checkpoint after the fix
5. **Update plan** — adjust remaining sub-tasks if the fix changed assumptions
6. **Log** — record the failure and adjustment in `.github/knowledge/iteration-log.md`

## EMSX-Specific Patterns

- Backend changes require restart — include "restart backend" as a sub-task after Python edits
- Bloomberg field additions require coordinated changes across 3-5 files — decompose as: subscription → backend model → parser → frontend type → UI column
- Frontend type changes must match backend model — verify types/index.ts after backend model changes
