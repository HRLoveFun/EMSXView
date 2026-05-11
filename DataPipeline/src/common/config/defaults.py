"""
Default processing parameters and format strings for the EMSX fill data pipeline.

All processing defaults, parallelization settings, date/time format strings,
filter rules, and policy dictionaries are defined here.
Merged from the original FormatsConfig (which was too small for its own file).
"""

from __future__ import annotations

from typing import Any

import numpy as np


class DefaultsConfig:
    """Default parameter and format configuration constants.

    Processing parameters, batch sizes, date/time formats, parallelization
    limits, filter rules, and execution history policies.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # DATE & TIME FORMATS
    # ═══════════════════════════════════════════════════════════════════════

    DATE_FORMAT: str = "%Y%m%d"                         # YYYYMMDD
    DATE_FORMAT_DASH: str = "%Y-%m-%d"                  # YYYY-MM-DD
    TIME_FORMAT: str = "%H:%M:%S"                       # HH:MM:SS
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"          # Combined

    # EMSX DateTimeOfFill format (NY time with offset)
    EMSX_DATETIME_FORMATS: list = [
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # LOG FORMATS
    # ═══════════════════════════════════════════════════════════════════════

    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    LOG_DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"

    # ═══════════════════════════════════════════════════════════════════════
    # PROCESSING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # [UNUSED] These legacy config values are kept for reference only.
    # They are NOT referenced anywhere in the current codebase.
    # Actual batch sizes are controlled per-module:
    #   - fill_fetch.py:       date batching via --batch-size flag (parallel mode only)
    #   - fill_processor.py:   EUR ticker resolution chunk_size=100 (xbbg blp.bdp)
    #   - raw_fills_db.py:     executememany (full day per transaction)
    CHUNKSIZE: int = 100_000                            # [UNUSED] Legacy row-chunk size
    BATCH_SIZE: int = 1_000                              # [UNUSED] Legacy API batch size
    FLOAT_TYPE: type = np.float32
    INT_TYPE: type = np.int32

    # ═══════════════════════════════════════════════════════════════════════
    # CLEANING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # ExecType values to filter OUT (not actual fills)
    EXECTYPE_FILTER_OUT: set = {"DFD"}  # Done For Day

    # First-run lookback days (calendar days, not trading days)
    FIRST_RUN_LOOKBACK_DAYS: int = 60

    # Raw BDIB ticker filter whitelist by exchange code (from ticker_repository).
    # Example: ["US", "JP", "LN"]
    BDID_EXCHANGE: list[str] = [
        "AU", "AV", "BB", "FH", "FP", "GA", "GR", "ID", "IJ", "IM",
        "IN", "JP", "KS", "LN", "MK", "NA", "NO", "PL", "SJ", "SM",
        "SP", "SS", "SW", "US",
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # PARALLELIZATION PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    # Max threads for date-level parallelism in S2 (ProcessRawFills) and S3 (AggregateFills).
    # Each thread uses its own DB connection. Set to 1 to disable parallelism.
    MAX_PARALLEL_DATES: int = 4

    # Max threads for ticker-level parallelism in S5 (IntegrateBDIB).
    # Bloomberg API session limit is ~3 concurrent requests.
    MAX_PARALLEL_TICKERS: int = 3

    # SQLite busy handling for concurrent pipeline stages.
    SQLITE_CONNECT_TIMEOUT_SEC: int = 30
    SQLITE_BUSY_TIMEOUT_MS: int = 30_000

    # Latest prior trading day becomes eligible for BDIB fetches only after this
    # local hour on the following calendar day. Before that, the pipeline uses
    # the previous safe trading day to avoid xbbg near-real-time warnings.
    BDIB_LATEST_READY_HOUR_LOCAL: int = 18

    # ═══════════════════════════════════════════════════════════════════════
    # LOGGING PARAMETERS
    # ═══════════════════════════════════════════════════════════════════════

    LOG_RETENTION_DAYS: int = 30
    LOG_DEBUG_RETENTION_DAYS: int = 7

    # ═══════════════════════════════════════════════════════════════════════
    # EXECUTION HISTORY POLICIES
    # ═══════════════════════════════════════════════════════════════════════

    EXECUTION_HISTORY_SOURCE_POLICY: dict[str, tuple[str, ...]] = {
        "fills": (
            "emsx.history:GetFills",
        ),
        "orders": (
            "costview.fill-rollup",
            "executionview.orders_projection",
        ),
        "routes": (
            "costview.fill-rollup",
            "executionview.routes_projection",
        ),
        "route_events": (
            "emsx.history:GetFills",
            "executionview.audit_events",
        ),
    }

    EXECUTION_HISTORY_REFRESH_POLICY: dict[str, str] = {
        "fills": "incremental-per-fetch",
        "orders": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "routes": "rebuild-per-processed-date;patch-from-executionview-when-available",
        "route_events": "append-per-fill;patch-from-executionview-audit-when-available",
    }
