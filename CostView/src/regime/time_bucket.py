"""
Time-of-day bucket assignment for fills.

Rationale
---------
Each fill is tagged with a TOD bucket label so that attribution can be sliced
by intraday phase (open auction, morning, midday, afternoon, closing auction).
Execution costs differ markedly across these phases (wider spread / lower
liquidity / closing auction concentration).

This module is intentionally narrow:
- Only 5 markets are enabled: US, AU, JP, LN, EU.
- Other markets (HK/KS/IN/CH/...) leave time_bucket = NULL.
- Per-market bucket boundaries are hardcoded below to keep the assignment
  deterministic and inspectable. Session config in ref_market_mapping is
  authoritative for backtesting boundaries; if it ever drifts from the table
  here, update both.

Public API
----------
- assign_time_bucket(market_code, exchange_exec_time) -> Optional[str]
- ENABLED_MARKETS: frozenset of supported market codes
- TOD_BUCKETS: dict[market_code, list[(start, end, name)]]
"""
from __future__ import annotations

from typing import List, Optional, Tuple

# (start_hhmm, end_hhmm, bucket_name). End is exclusive; ranges must be
# monotonic non-overlapping ascending. JP's lunch gap is an explicit
# `lunch_break` window (rare but possible for off-book / cross prints).
_BucketSpec = Tuple[str, str, str]

TOD_BUCKETS: dict[str, List[_BucketSpec]] = {
    "US": [
        ("09:30", "10:00", "open_30m"),
        ("10:00", "12:00", "morning"),
        ("12:00", "14:00", "midday"),
        ("14:00", "15:30", "afternoon"),
        ("15:30", "16:00", "close_30m"),
    ],
    "AU": [
        ("10:00", "10:30", "open_30m"),
        ("10:30", "12:00", "morning"),
        ("12:00", "14:00", "midday"),
        ("14:00", "15:40", "afternoon"),
        ("15:40", "16:10", "close_30m"),
    ],
    "LN": [
        ("08:00", "08:30", "open_30m"),
        ("08:30", "12:00", "morning"),
        ("12:00", "14:00", "midday"),
        ("14:00", "16:05", "afternoon"),
        ("16:05", "16:35", "close_30m"),
    ],
    "EU": [
        ("09:00", "09:30", "open_30m"),
        ("09:30", "12:00", "morning"),
        ("12:00", "15:00", "midday"),
        ("15:00", "17:00", "afternoon"),
        ("17:00", "17:30", "close_30m"),
    ],
    "JP": [
        ("09:00", "09:30", "open_30m"),
        ("09:30", "11:30", "morning"),
        ("11:30", "12:30", "lunch_break"),
        ("12:30", "15:00", "afternoon"),
        ("15:00", "15:30", "close_30m"),
    ],
}

ENABLED_MARKETS = frozenset(TOD_BUCKETS.keys())


def _parse_hhmm(value: str) -> Optional[int]:
    """Convert 'HH:MM' or 'HH:MM:SS' (exchange-local) to minutes-since-midnight.

    Returns None on bad input.
    """
    if not isinstance(value, str) or len(value) < 5:
        return None
    try:
        hh = int(value[0:2])
        mm = int(value[3:5])
    except ValueError:
        return None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return hh * 60 + mm


def assign_time_bucket(market_code: str, exchange_exec_time: str) -> Optional[str]:
    """Return TOD bucket name for a fill, or None if outside scope.

    Parameters
    ----------
    market_code : Bloomberg market code (e.g. 'US', 'JP').
    exchange_exec_time : exchange-local time string 'HH:MM' or 'HH:MM:SS'.

    Returns None when the market is not enabled, the time is unparseable,
    or the time falls outside any configured bucket window (e.g. pre-open
    extended-hours fills).
    """
    if market_code not in TOD_BUCKETS:
        return None
    minute = _parse_hhmm(exchange_exec_time)
    if minute is None:
        return None
    for start, end, name in TOD_BUCKETS[market_code]:
        s = _parse_hhmm(start)
        e = _parse_hhmm(end)
        if s is None or e is None:
            continue
        if s <= minute < e:
            return name
    return None
