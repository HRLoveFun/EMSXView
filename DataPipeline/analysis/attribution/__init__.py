"""
CostView attribution layer (M2).

Computes per-fill execution-quality metrics:
  - IS slippage vs arrival mid
  - VWAP slippage vs interval VWAP
  - Post-fill reversal at 1 / 5 / 30 minutes

Joinable to fill_regime_labels for regime-conditional analysis.

Architecture (v2 — repository-decoupled):
  - dto.py: Data Transfer Objects (pure data, no DB knowledge) → now in DataPipeline/storage/dto.py
  - protocols.py: Repository Protocol interfaces (structural subtyping)
  - repositories.py: Concrete SQL implementations (all sqlite3 knowledge here)
  - writer.py, aggregator.py, recommender.py: Business logic depends on protocols
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
