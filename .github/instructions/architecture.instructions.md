---
description: "Use when reviewing architecture, proposing structural changes, assessing technical debt, or planning refactoring. Covers architecture decisions and incremental improvement."
applyTo: ["ExecutionView/backend/api/main.py", "ExecutionView/frontend/src/**", "CostView/src/**"]
---
# Architecture Review Guidelines

## Before Structural Changes

1. Read `.github/knowledge/architecture-decisions.md` for existing decisions that may constrain or guide the change
2. If the change contradicts an existing decision, document why the decision should be updated before proceeding
3. Check if the affected area has pending review dates â€” if overdue, flag it

## Code Health Indicators

Flag for review when:
- A file exceeds **500 lines** (current hotspot: `ExecutionView/backend/api/main.py` at ~3695 lines)
- A function exceeds **50 lines**
- A module has more than **5 direct dependencies**
- The same pattern is copy-pasted in **3+ places**
- A test file doesn't exist for a module with business logic

## Refactoring Rules

1. **Incremental only**: Every refactoring step must leave the system functional and all tests passing
2. **Test gates**: Run tests after each step; if any fail, stop and fix before continuing
3. **No big-bang rewrites**: Propose extraction of one concern at a time (e.g., extract Bloomberg session management from main.py into a separate module)
4. **Document the decision**: Add an entry to `.github/knowledge/architecture-decisions.md` with context, decision, consequences, and review date

## Feature Evolution

For existing features, consider:
- **Usage**: Is the feature actively used? (Check logs, UI analytics if available)
- **Maintenance cost**: How often does it break or need updates?
- **Brittleness**: Does it depend on undocumented Bloomberg behavior?

If a feature is underutilized or brittle, propose: deprecation, simplification, or rewrite with justification.

