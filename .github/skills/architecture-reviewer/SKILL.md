---
name: architecture-reviewer
description: "Review project architecture and propose improvements. Use after major features, for technical debt analysis, weekly architecture health checks, or before starting large refactoring work."
---
# Architecture Reviewer

## When to Use
- After completing a major feature
- During periodic architecture reviews (recommended: biweekly)
- When a file grows beyond health thresholds
- Before proposing structural changes
- When evaluating technical debt priorities

## Procedure

### Step 1: Inventory
- List all modules and their sizes (line counts, file counts)
- Identify files exceeding thresholds: >500 lines (warning), >1000 lines (critical)
- Map dependencies between modules

### Step 2: Check Decisions
- Read [architecture-decisions.md](../../knowledge/architecture-decisions.md)
- For each decision with a passed review date: evaluate if the decision still holds
- Flag decisions that conflict with current implementation

### Step 3: Identify Hotspots
- **Size hotspots**: Files that are too large (current: `main.py` at ~3695 lines)
- **Churn hotspots**: Files changed most frequently (check git log)
- **Coupling hotspots**: Modules with too many cross-dependencies
- **Test gaps**: Modules with business logic but no test coverage

### Step 4: Propose Improvements
For each hotspot, use the [review checklist](./references/review-checklist.md) to propose:
- **Incremental refactoring** with explicit test gates at each step
- **Dependency decoupling** to reduce blast radius of changes
- **Test additions** for uncovered business logic

### Step 5: Feature Evolution
For existing features:
- Check usage (logs, error frequency, maintenance cost)
- If underutilized or brittle: propose deprecation, simplification, or rewrite
- Document the proposal as a draft decision

### Step 6: Update Knowledge Base
- Add/update entries in [architecture-decisions.md](../../knowledge/architecture-decisions.md)
- Append to [iteration-log.md](../../knowledge/iteration-log.md): date, type=architecture, trigger, action, outcome

## Reference
- [Review Checklist](./references/review-checklist.md) — EMSX-specific checklist, refactoring patterns, health thresholds
