"""TCA query service protocol — defines the interface for TCA query implementations.

This protocol breaks the circular dependency between platform_data and CostView.
Instead of platform_data importing CostView directly, CostView registers its
TcaQueryService implementation at startup via dependency injection.

Usage:
    # In application startup (e.g. CostView/api/main.py):
    from platform_data.adapters.tca_bridge import register_tca_service_impl
    register_tca_service_impl(your_tca_service_instance)

    # In consuming code:
    from platform_data.adapters.tca_bridge import get_tca_query_service
    svc = get_tca_query_service()
    report = svc.build_tca_report(filters)
"""

from __future__ import annotations

from typing import Protocol

from platform_data.contracts.tca_contracts import (
    ScorecardFilters,
    ScorecardReport,
    TcaFilters,
    TcaReport,
)


class TcaQueryServiceProtocol(Protocol):
    """Protocol for TCA query service implementations.

    Any implementation must provide these two public methods. The concrete
    implementation (CostView.src.tca_query_service.TcaQueryService) satisfies
    this protocol.
    """

    def build_tca_report(self, filters: TcaFilters) -> TcaReport:
        """Build a full TCA report for the given filters.

        Queries processed fills, computes TCA metrics, enriches with market
        context, and returns a structured TcaReport.
        """
        ...

    def build_scorecard(self, filters: ScorecardFilters) -> ScorecardReport:
        """Build a broker/strategy cohort scorecard for the given filters.

        Aggregates TCA metrics across cohorts and returns a ScorecardReport
        with per-cohort statistics.
        """
        ...
