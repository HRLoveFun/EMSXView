"""Cross-module data contracts for the EMSX platform.

This package defines the **only legal** data types that may cross module
boundaries (ExecutionView ↔ CostView ↔ MarketView). Each contract is a
pure dataclass or constant — no business logic, no DB imports.

Ownership rule:
  - CostView owns the data; contracts are the projection it publishes.
  - Consumers (ExecutionView, MarketView) import from this package only.
  - When CostView's internal DTOs evolve, contracts are updated here with
    an explicit version bump so downstream breakage is caught early.
"""

from .tca_contracts import (
    SCORECARD_COHORTS,
    ScorecardCohortMetrics,
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaOrderSummary,
    TcaReport,
    TcaRouteDetail,
)
