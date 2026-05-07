"""
Cross-table statistics utility for processed_fills.db.

Provides a single ``get_processing_stats()`` function that queries row
counts across all tables.  This is the only method in the original
``ProcessedFillsDB`` that genuinely spans all domains, so it lives
in its own module rather than in any single repository.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict

from DataPipeline.src.common.processing_config import ProcessingConfig as Config
from ._base import BaseProcessedFillsRepo


def get_processing_stats(repo: BaseProcessedFillsRepo) -> Dict[str, Any]:
    """Get summary statistics across all tables in ``processed_fills.db``.

    Parameters
    ----------
    repo : BaseProcessedFillsRepo
        Any repository instance with the correct ``db_path`` and
        ``_get_conn()`` method.

    Returns
    -------
    Dict[str, Any]
        Mapping of table name → row count, plus a
        ``"processing_stages"`` sub-dict with stage → distinct date count.
    """
    conn = repo._get_conn()
    try:
        stats: Dict[str, Any] = {}
        for table in [
            Config.PROCESSED_FILLS_TABLE,
            Config.AGG_10S_TABLE,
            Config.AGG_1MIN_TABLE,
            Config.ORDER_HISTORY_TABLE,
            Config.ROUTE_HISTORY_TABLE,
            Config.ROUTE_EVENT_HISTORY_TABLE,
            Config.AGG_PROCESSED_FILLS_TABLE,
            Config.PROCESSED_FILLS_1MIN_TABLE,
            Config.ORDER_LABEL_TABLE,
        ]:
            try:
                cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                stats[table] = 0

        try:
            cursor = conn.execute(
                f"""SELECT stage, COUNT(DISTINCT order_as_of_date)
                    FROM {Config.PROCESSING_LOG_TABLE}
                    GROUP BY stage"""
            )
            stats["processing_stages"] = {r[0]: r[1] for r in cursor.fetchall()}
        except sqlite3.OperationalError:
            stats["processing_stages"] = {}

        return stats
    finally:
        conn.close()