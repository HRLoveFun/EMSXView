# CostView Legacy Frontend Prototype

This directory is a legacy prototype surface.

Current status:

- The canonical CostView UI lives in `Execution/frontend/src/modules/costview/`.
- This directory does not define an independent frontend application shell.
- The legacy prototype source has been archived to `CostView/frontend/archive/2026-04-22/src/`.
- It should not receive new product features unless a deliberate re-platforming decision is recorded first.

Rules:

1. Do not treat `CostView/frontend/src/` as the active user entry point.
2. Do not add new routing, state, or API integration work here by default.
3. If a prototype is still useful for reference, use the archived copy and migrate any production-worthy logic into the shared frontend shell.

Canonical locations:

- Active frontend shell: `Execution/frontend/src/App.tsx`
- Active CostView module: `Execution/frontend/src/modules/costview/CostViewModule.tsx`
- Active CostView analytics/data layer: `CostView/src/`

Disposition:

- Classification: downgraded to legacy prototype
- Current archived source: `CostView/frontend/archive/2026-04-22/src/`
- Target end state: delete the archived prototype once no remaining reference value exists