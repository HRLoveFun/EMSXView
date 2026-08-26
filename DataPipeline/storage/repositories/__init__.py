"""Concrete SQLite repository implementations.

All SQL and sqlite3 knowledge is encapsulated here. Business logic
imports these classes directly (no Protocol indirection).

Each repository uses ConnectionManager for connections, ensuring
standard pragmas and access tier enforcement.
"""

from ._base import BaseRepository  # noqa: F401
from .fills import SqliteFillReadRepository, SqliteFillWriteRepository  # noqa: F401
from .raw_fills import SqliteRawFillReadRepository, SqliteRawFillWriteRepository  # noqa: F401
from .market_data import SqliteMarketDataReadRepository, SqliteMarketDataWriteRepository  # noqa: F401
from .integrated import SqliteIntegratedReadRepository, SqliteIntegratedWriteRepository  # noqa: F401
from .regime import SqliteRegimeReadRepository, SqliteRegimeWriteRepository  # noqa: F401
from .fx_rates import SqliteFxRatesRepository  # noqa: F401
from .bdib_fetch_history import SqliteBdibFetchHistoryRepository  # noqa: F401

__all__ = [
    "BaseRepository",
    "SqliteFillReadRepository",
    "SqliteFillWriteRepository",
    "SqliteRawFillReadRepository",
    "SqliteRawFillWriteRepository",
    "SqliteMarketDataReadRepository",
    "SqliteMarketDataWriteRepository",
    "SqliteIntegratedReadRepository",
    "SqliteIntegratedWriteRepository",
    "SqliteRegimeReadRepository",
    "SqliteRegimeWriteRepository",
    "SqliteFxRatesRepository",
    "SqliteBdibFetchHistoryRepository",
]
