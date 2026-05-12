"""CostView storage — convenience re-exports (backward compat).

New code should import directly from DataPipeline:
    from DataPipeline.storage.repositories.regime import (
        SqliteRegimeReadRepository,
        SqliteRegimeWriteRepository,
    )
"""
from typing import Optional
from pathlib import Path
import pandas as pd
from DataPipeline.storage.repositories.regime import SqliteRegimeReadRepository


def get_fill_labels(
    date_iso: Optional[str] = None, market_code: Optional[str] = None,
    config_version: Optional[str] = None, db_path: Optional[Path] = None,
) -> pd.DataFrame:
    repo = SqliteRegimeReadRepository()
    return repo.get_fill_labels(date_iso, market_code, config_version, db_path)


def get_daily_index(
    start: str, end: str, market_code: Optional[str] = None, db_path: Optional[Path] = None,
) -> pd.DataFrame:
    repo = SqliteRegimeReadRepository()
    return repo.get_daily_index(start, end, market_code, db_path)


def get_audit_runs(
    stage_name: Optional[str] = None, limit: int = 50, db_path: Optional[Path] = None,
) -> pd.DataFrame:
    repo = SqliteRegimeReadRepository()
    return repo.get_audit_runs(stage_name, limit, db_path)


__all__ = ["get_fill_labels", "get_daily_index", "get_audit_runs"]
