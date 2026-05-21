"""
Helpers for audit_attribution_config_versions:
- get_active_config(): return the active attribution config row.
- seed_default_config(): seed 'attr_v0' if none exists.

Both functions support two calling conventions:
  1. (Preferred) Pass an AttributionConfigRepository directly.
  2. (Legacy) Pass db_path to auto-create a repository.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from DataPipeline.analysis.regime.schema import REGIME_DB_PATH, connect, ensure_schema_current

if TYPE_CHECKING:
    from .protocols import AttributionConfigRepository

logger = logging.getLogger(__name__)

DEFAULT_VERSION_ID = "attr_v0"


@dataclass(frozen=True)
class ActiveAttributionConfig:
    version_id: str
    bench_methods: List[str]          # e.g. ['arrival_mid','interval_vwap']
    reversal_windows_min: List[int]   # e.g. [1, 5, 30]
    winsor_pct: float
    adv_window_days: int
    bootstrap_n: int
    min_cell_n: int
    description: Optional[str]


def _row_to_config(row) -> ActiveAttributionConfig:
    """Convert a raw SQL row tuple to ActiveAttributionConfig (legacy helper)."""
    return ActiveAttributionConfig(
        version_id=row[0],
        bench_methods=[s.strip() for s in str(row[1]).split(",") if s.strip()],
        reversal_windows_min=[int(x.strip()) for x in str(row[2]).split(",") if x.strip()],
        winsor_pct=float(row[3]),
        adv_window_days=int(row[4]),
        bootstrap_n=int(row[5]),
        min_cell_n=int(row[6]),
        description=row[7],
    )


def _dto_to_config(dto) -> ActiveAttributionConfig:
    """Convert an AttributionConfigDTO to ActiveAttributionConfig."""
    from DataPipeline.storage.dto import AttributionConfigDTO
    return ActiveAttributionConfig(
        version_id=dto.version_id,
        bench_methods=dto.bench_methods,
        reversal_windows_min=dto.reversal_windows_min,
        winsor_pct=dto.winsor_pct,
        adv_window_days=dto.adv_window_days,
        bootstrap_n=dto.bootstrap_n,
        min_cell_n=dto.min_cell_n,
        description=dto.description,
    )


def get_active_config(
    db_path: Path = REGIME_DB_PATH,
    *,
    config_repo: Optional["AttributionConfigRepository"] = None,
) -> Optional[ActiveAttributionConfig]:
    """Return active attribution config (is_active=1), or None.

    Supports two calling conventions:
      1. Pass config_repo directly (preferred, no DB knowledge needed).
      2. Pass db_path to auto-create a repository (legacy).
    """
    if config_repo is None:
        from .repositories import SqliteAttributionConfigRepository
        config_repo = SqliteAttributionConfigRepository(db_path)

    dto = config_repo.get_active_config()
    if dto is None:
        return None
    return _dto_to_config(dto)


def seed_default_config(
    db_path: Path = REGIME_DB_PATH,
    *,
    config_repo: Optional["AttributionConfigRepository"] = None,
) -> str:
    """Insert 'attr_v0' default config if no rows exist; return active version_id.

    Defaults match user-approved M2 plan:
      arrival_mid + interval_vwap; reversal 1/5/30 min; winsor 1%;
      adv_window 30d; bootstrap 5000; min_cell 30.

    Supports two calling conventions (same as get_active_config).
    """
    if config_repo is None:
        from .repositories import SqliteAttributionConfigRepository
        config_repo = SqliteAttributionConfigRepository(db_path)

    return config_repo.seed_default_config()
