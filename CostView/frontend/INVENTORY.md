# CostView Legacy Frontend Inventory

This inventory classifies the legacy prototype files that were archived from `CostView/frontend/src/` to `CostView/frontend/archive/2026-04-22/src/`.

## Decision Matrix

| Legacy file | Current shell successor | Decision | Reason |
|---|---|---|---|
| `services/tca-api.ts` | `Execution/frontend/src/modules/costview/services/api.ts` | Archived | Shell service is canonical and already richer (`fetchAllFilteredOrders`, update polling, shell-aligned auth handling) |
| `pages/TCAPage.tsx` | `Execution/frontend/src/modules/costview/CostViewModule.tsx` + `components/AnalysisView.tsx` | Archived | Legacy page composes one linear TCA flow; shell module now owns the actual user journey |
| `components/tca/TcaFilterPanel.tsx` | `Execution/frontend/src/modules/costview/components/TcaFilterWorkbench.tsx` | Archived | Shell version already supersedes it with persisted filter form state and warning-only controls |
| `components/tca/TcaOrderTable.tsx` | `Execution/frontend/src/modules/costview/components/TcaOrderTable.tsx` | Archived | Shell version adds threshold-aware alert states and integrated route expansion |
| `components/tca/TcaRouteTable.tsx` | `Execution/frontend/src/modules/costview/components/TcaRouteTable.tsx` | Archived | Same responsibility already exists in the canonical shell module |
| `components/tca/PriceDynamicChart.tsx` | `Execution/frontend/src/modules/costview/components/PriceDynamicsChart.tsx` | Archived for reference | Naming differs but shell chart is the authoritative implementation |
| `components/tca/VolumeDynamicChart.tsx` | `Execution/frontend/src/modules/costview/components/VolumeDynamicsChart.tsx` | Archived for reference | Shell chart is the authoritative implementation |

## Summary

- No remaining legacy component is the canonical implementation.
- The active `CostView/frontend/src/` surface has been cleared and replaced with a marker README.
- The archived prototype can now be deleted in a future pass once no remaining reference value exists.