"""
[BACKWARD COMPAT] Re-exports ``FillFetchDatabase`` and ``compute_data_hash``.

New code should import directly from:
    DataPipeline.storage.repositories.fetch_history
"""

from typing import Optional

from DataPipeline.storage.repositories.fetch_history import (  # noqa: F401
    SqliteFetchHistoryRepository,
    compute_data_hash,
)


class FillFetchDatabase(SqliteFetchHistoryRepository):
    """Backward-compatible ``FillFetchDatabase`` accepting an optional ``db_path``.

    Legacy usage::

        db = FillFetchDatabase(db_path="/custom/path/history.db")

    This class adapts the old string-based constructor to the new
    ``ConnectionManager``-based repository API.
    """

    def __init__(self, db_path: Optional[str] = None):
        from pathlib import Path
        if db_path is not None:
            from DataPipeline.storage.connection import (
                ConnectionManager,
                DB_FETCH_HISTORY,
            )
            p = Path(db_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            mgr = ConnectionManager(path_overrides={DB_FETCH_HISTORY: p})
        else:
            mgr = None  # BaseRepository default
        super().__init__(connection_manager=mgr)


# Re-export for convenience
__all__ = ["FillFetchDatabase", "SqliteFetchHistoryRepository", "compute_data_hash"]
