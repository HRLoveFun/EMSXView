"""Repository implementations for the CostView database subsystem.

All SQL and sqlite3 knowledge is encapsulated here. Business logic
depends on Protocol interfaces (db.protocols), never on these concrete
classes directly.

Each repository uses ConnectionManager for connections, ensuring
standard pragmas and access tier enforcement.
"""

from ._base import BaseRepository  # noqa: F401
from .fills_read import SqliteFillReadRepository  # noqa: F401
from .fills_write import SqliteFillWriteRepository  # noqa: F401
from .raw_fills_read import SqliteRawFillReadRepository  # noqa: F401
from .raw_fills_write import SqliteRawFillWriteRepository  # noqa: F401
from .market_data_read import SqliteMarketDataReadRepository  # noqa: F401
from .market_data_write import SqliteMarketDataWriteRepository  # noqa: F401
from .integrated import SqliteIntegratedReadRepository, SqliteIntegratedWriteRepository  # noqa: F401
from .regime import SqliteRegimeReadRepository, SqliteRegimeWriteRepository  # noqa: F401

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
]
