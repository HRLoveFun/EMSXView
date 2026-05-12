"""Processing parameters — formats, types, exchange filters, parallelization."""

from __future__ import annotations

import numpy as np


class ProcessingConfig:
    DATE_FORMAT: str = "%Y%m%d"
    DATE_FORMAT_DASH: str = "%Y-%m-%d"
    TIME_FORMAT: str = "%H:%M:%S"
    DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"
    EMSX_DATETIME_FORMATS: list = [
        "%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",    "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",   "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",      "%Y-%m-%dT%H:%M:%S",
    ]

    FLOAT_TYPE: type = np.float32
    INT_TYPE: type = np.int32
    EXECTYPE_FILTER_OUT: set = {"DFD"}
    FIRST_RUN_LOOKBACK_DAYS: int = 60
    BDID_EXCHANGE: list[str] = [
        "AU", "AV", "BB", "FH", "FP", "GA", "GR", "ID", "IJ", "IM",
        "IN", "JP", "KS", "LN", "MK", "NA", "NO", "PL", "SJ", "SM",
        "SP", "SS", "SW", "US",
    ]

    MAX_PARALLEL_DATES: int = 1
    MAX_PARALLEL_TICKERS: int = 1
    SQLITE_CONNECT_TIMEOUT_SEC: int = 30
    SQLITE_BUSY_TIMEOUT_MS: int = 30_000
    BDIB_LATEST_READY_HOUR_LOCAL: int = 18
