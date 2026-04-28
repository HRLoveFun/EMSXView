"""
CostView attribution layer (M2).

Computes per-fill execution-quality metrics:
  - IS slippage vs arrival mid
  - VWAP slippage vs interval VWAP
  - Post-fill reversal at 1 / 5 / 30 minutes

Joinable to fill_regime_labels for regime-conditional analysis.
"""
from .config import (
    ActiveAttributionConfig,
    get_active_config,
    seed_default_config,
)

__all__ = [
    "ActiveAttributionConfig",
    "get_active_config",
    "seed_default_config",
]
