"""
Bloomberg data-source adapters for the regime layer.

This module is a placeholder/interface stub. Concrete fetchers will be
implemented in M1 step 5 (daily calculators):
- IndexHistoryFetcher: blp.bdh() for benchmark/vol indices (PX_LAST, VOLATILITY_*, TURNOVER, MOV_AVG_*, RSI_30D)
- 52W high/low: derived from PX_LAST rolling 252-day max/min (NOT a Bloomberg mnemonic)

Keeping the interface here lets the storage layer stub (CostView/src/storage/)
abstract over SQLite vs Parquet without touching fetcher code.
"""
from __future__ import annotations

from typing import Protocol, List
from datetime import date


class IndexHistoryFetcher(Protocol):
    """Fetches daily history for one Bloomberg index ticker."""

    def fetch(self, ticker: str, fields: List[str], start: date, end: date):
        """Return a tidy DataFrame indexed by date with one column per field."""
        ...
