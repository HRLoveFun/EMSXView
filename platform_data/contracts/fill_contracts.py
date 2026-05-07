"""Fill-related cross-module contracts.

Defines the stable data types that CostView exposes for fill/order
data consumed by ExecutionView and other modules.
"""

from __future__ import annotations

# ── Scorecard cohort dimension registry ────────────────────────────────────────
# The authoritative list of valid cohort dimensions for the scorecard API.
# Previously defined in CostView.src.tca_query_service; now owned by the
# contract layer so ExecutionView can validate without importing CostView.

SCORECARD_COHORTS: tuple[str, ...] = (
    "broker",
    "strategy",
    "broker_strategy",
    "asset_class",
    "time_of_day",
    "liquidity_adv20",
    "volatility",
)
