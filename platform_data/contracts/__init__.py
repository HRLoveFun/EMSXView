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

# TCA / Scorecard contracts
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

# Protocol interfaces
from .protocols import (
    ConfigProtocol,
    ConnectionManagerProtocol,
)

from .tca_service_protocol import (
    TcaQueryServiceProtocol,
)

# Market-view contracts
from .market_contracts import (
    MarketAlert,
    MarketCandidatePayload,
    MarketCandidateRow,
    MarketDailySnapshotRow,
    MarketSnapshot,
    MarketSnapshotFilters,
    MarketSnapshotSort,
    MarketStockPool,
)

# Intraday-feature contracts
from .intraday_contracts import (
    INTRADAY_BUCKET_OPTIONS,
    INTRADAY_DEFAULT_BUCKET_MINUTES,
    INTRADAY_MAX_TICKERS,
    IntradayFeatureBucket,
    IntradayFeatureSnapshot,
    IntradayTickerFeatures,
)

# Execution-history contracts
from .execution_contracts import (
    ExecutionHistoryFillRow,
    ExecutionHistoryFillSnapshot,
    ExecutionHistoryOrderSummaryRow,
    ExecutionHistoryOrderSummarySnapshot,
    ExecutionHistoryRouteSummaryRow,
    ExecutionHistoryRouteSummarySnapshot,
)

# Handoff contracts
from .handoff_contracts import (
    BrokerStrategyRecommendation,
    ExecutionCandidateHandoff,
    ExecutionPostTradeHandoff,
    HandoffMetadata,
    _new_trace_id,
    _now_iso,
)
