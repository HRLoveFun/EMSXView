"""
Exchange → Timezone mapping and conversion helpers.

Derived from xbbg's exch.yml / assets.yml configuration. Maps Bloomberg
exchange codes used in EMSX fill data to IANA timezone strings so that
DateTimeOfFill (reported in NY time) can be converted to local exchange time.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

# ── Bloomberg exchange code → IANA timezone ─────────────────────────────────
# Sources:
#   xbbg/markets/config/exch.yml   (session definitions)
#   xbbg/markets/config/assets.yml (exchange-code → exch-name mapping)
#
# The EMSX "Exchange" field uses the short Bloomberg exchange code
# (e.g. "US", "JP", "LN"), which we map to the corresponding IANA tz.

EXCHANGE_TIMEZONE: dict[str, str] = {
    # ── APAC ────────────────────────────────────────────────────────────────
    "AU": "Australia/Sydney",
    "NZ": "Australia/Sydney",       # xbbg treats NZ on Sydney tz
    "JP": "Asia/Tokyo",
    "JT": "Asia/Tokyo",
    "KS": "Asia/Seoul",
    "TT": "Asia/Taipei",
    "HK": "Asia/Hong_Kong",
    "CH": "Asia/Shanghai",
    "CG": "Asia/Shanghai",
    "CS": "Asia/Shanghai",
    "IN": "Asia/Calcutta",
    "IS": "Asia/Calcutta",
    "IB": "Asia/Calcutta",
    "SP": "Asia/Hong_Kong",         # Singapore uses HK tz in xbbg
    "MK": "Asia/Hong_Kong",         # Malaysia uses HK tz in xbbg
    "IJ": "Asia/Jakarta",
    # ── EMEA ────────────────────────────────────────────────────────────────
    "LN": "Europe/London",
    "LI": "Europe/London",
    "EU": "Europe/Berlin",          # Eurozone generic
    "GR": "Europe/Berlin",          # Germany/Frankfurt → Berlin
    "FP": "Europe/London",          # France/Paris → xbbg uses London for EquityFrance
    "IM": "Europe/Rome",            # Italy/Milan
    "SM": "Europe/London",          # Spain/Madrid → xbbg uses London for EquitySpain
    "SQ": "Europe/London",          # Spain alt
    "NA": "Europe/Amsterdam",
    "BB": "Europe/Brussels",
    "AV": "Europe/Vienna",
    "FH": "Europe/Helsinki",
    "NO": "Europe/Oslo",
    "DC": "Europe/Copenhagen",
    "SS": "Europe/Stockholm",
    "SW": "Europe/Zurich",
    "PW": "Europe/Warsaw",
    "PL": "Europe/Lisbon",
    "GA": "Europe/Athens",
    "ID": "Europe/London",          # Dublin
    "SJ": "Africa/Johannesburg",
    "IT": "Asia/Jerusalem",         # Tel Aviv
    # ── Americas ────────────────────────────────────────────────────────────
    "US": "America/New_York",
    "UQ": "America/New_York",       # NASDAQ
    "UA": "America/New_York",       # AMEX
    "UN": "America/New_York",       # NYSE
    "UP": "America/New_York",       # NYSE Arca
    "UW": "America/New_York",       # CBOE
    "UR": "America/New_York",       # NYSE Arca
    "CT": "America/New_York",       # NYSE composite
    "CN": "America/Toronto",
    "CF": "America/Toronto",        # Canada alt
    "BZ": "America/Sao_Paulo",
    "MM": "America/Mexico_City",
}

# NY timezone (EMSX DateTimeOfFill is reported in NY time)
NY_TZ = ZoneInfo("America/New_York")


def get_exchange_timezone(exchange_code: str) -> Optional[str]:
    """Return the IANA timezone string for a Bloomberg exchange code.

    Returns None if the exchange code is not recognized.
    """
    return EXCHANGE_TIMEZONE.get(exchange_code.strip().upper())


def convert_ny_to_local(dt_ny: datetime, exchange_code: str) -> Optional[datetime]:
    """Convert a NY-time datetime to the local exchange timezone.

    Args:
        dt_ny: Datetime in America/New_York (naive or aware).
               If naive, it is assumed to be NY time.
        exchange_code: Bloomberg exchange code (e.g. "JP", "LN").

    Returns:
        Timezone-aware datetime in the exchange's local timezone,
        or None if the exchange code is not recognized.
    """
    tz_name = get_exchange_timezone(exchange_code)
    if tz_name is None:
        return None

    local_tz = ZoneInfo(tz_name)

    # Ensure dt_ny is timezone-aware in NY
    if dt_ny.tzinfo is None:
        dt_ny = dt_ny.replace(tzinfo=NY_TZ)

    return dt_ny.astimezone(local_tz)


def get_local_time_str(dt_ny: datetime, exchange_code: str,
                       fmt: str = "%H:%M:%S") -> Optional[str]:
    """Convert NY datetime to local exchange time and return formatted string.

    Args:
        dt_ny: Datetime in NY time.
        exchange_code: Bloomberg exchange code.
        fmt: strftime format for the output.

    Returns:
        Formatted local time string, or None if exchange is unknown.
    """
    local_dt = convert_ny_to_local(dt_ny, exchange_code)
    if local_dt is None:
        return None
    return local_dt.strftime(fmt)


def get_local_date_str(dt_ny: datetime, exchange_code: str,
                       fmt: str = "%Y%m%d") -> Optional[str]:
    """Convert NY datetime to local exchange date string.

    Handles date-boundary crossings (e.g. 23:00 NY → next-day Tokyo).

    Args:
        dt_ny: Datetime in NY time.
        exchange_code: Bloomberg exchange code.
        fmt: strftime format for the output.

    Returns:
        Formatted local date string, or None if exchange is unknown.
    """
    local_dt = convert_ny_to_local(dt_ny, exchange_code)
    if local_dt is None:
        return None
    return local_dt.strftime(fmt)


def batch_convert_ny_to_local(
    dt_series: "pd.Series",
    exchange_series: "pd.Series",
) -> "pd.Series":
    """Vectorized NY→local timezone conversion, grouped by exchange code.

    Groups rows by exchange code (typically 5–15 unique per day), performs a
    single ZoneInfo lookup per group, and uses pandas vectorized tz_convert()
    for bulk conversion.  Falls back to NY time for unrecognized exchanges.

    Args:
        dt_series: pd.Series of datetime64[ns] (tz-naive, assumed NY) or
                   datetime64[ns, America/New_York].
        exchange_series: pd.Series of exchange code strings (e.g. "JP", "LN").

    Returns:
        pd.Series of tz-naive datetimes whose wall-clock values are already in
        each row's local exchange timezone. Returning naive local times avoids
        pandas coercing mixed timezones back into one shared timezone dtype.
    """
    import pandas as pd

    # Ensure dt is tz-aware in NY
    if dt_series.dt.tz is None:
        dt_ny = dt_series.dt.tz_localize("America/New_York")
    else:
        dt_ny = dt_series.dt.tz_convert("America/New_York")

    # Clean exchange codes
    exch_clean = exchange_series.astype(str).str.strip().str.upper()

    # Pre-allocate naive local wall-clock times using NY as the fallback.
    result = dt_ny.dt.tz_localize(None).copy()

    # Group by exchange code and convert each group in bulk
    for exch_code, group_idx in exch_clean.groupby(exch_clean).groups.items():
        if not exch_code or exch_code in ("", "NONE", "NAN"):
            continue

        tz_name = EXCHANGE_TIMEZONE.get(exch_code)
        if tz_name is None:
            continue

        # Convert to the exchange timezone, then drop tz info while preserving
        # the local wall-clock time so downstream string formatting remains
        # correct for mixed-exchange batches.
        group_dt = dt_ny.loc[group_idx]
        result.loc[group_idx] = group_dt.dt.tz_convert(tz_name).dt.tz_localize(None)

    return result
