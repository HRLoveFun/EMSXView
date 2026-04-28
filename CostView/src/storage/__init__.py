"""
CostView/src/storage/ — unified read interface stub.

Goal (post-M1): centralize all DB access so callers stop opening sqlite3 connections
directly. M1 ships read-only helpers for the regime layer; raw_fills / processed_fills
write paths remain on their existing dedicated DB classes (raw_fills_db.py,
processed_fills_db.py) until a follow-up sweep.

Public API (M1):
    from CostView.src.storage import regime_reader

    regime_reader.get_fill_labels(date_iso, market_code=None, config_version=None)
    regime_reader.get_daily_index(start, end, market_code=None)
    regime_reader.get_audit_runs(stage_name=None, limit=50)
"""
from CostView.src.storage import regime_reader  # noqa: F401

__all__ = ["regime_reader"]
