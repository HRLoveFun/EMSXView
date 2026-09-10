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
    "NZ": "Pacific/Auckland",       # 新西兰 NZX 实际时区（UTC+12/+13）
    "JP": "Asia/Tokyo",
    "JT": "Asia/Tokyo",
    "KS": "Asia/Seoul",
    "TT": "Asia/Taipei",
    "HK": "Asia/Hong_Kong",
    "CH": "Asia/Shanghai",
    "CG": "Asia/Shanghai",
    "CS": "Asia/Shanghai",
    "C1": "Asia/Shanghai",         # Nth SSE-SEHK (沪港通) — 2026-08-03
    "IN": "Asia/Calcutta",
    "IS": "Asia/Calcutta",
    "IB": "Asia/Calcutta",
    # ── 修复 (2026-07-02): Bloomberg EMSX 对 NSE 印度订单返回的 Exchange code
    # 是 "MUMBAI" (Bombay Stock Exchange), 而非 "IN"/"IS"/"IB"。
    # 缺失 MUMBAI 映射导致 2026-04-07 scope 切换重写 240 行 (5 个 OrderId, 5 个交易日)
    # order_as_of_date / exchange_exec_time 字段全部写 NULL, 下游 S2 抛错。
    # 经验教训: EMSX 实际 Exchange code 与 Bloomberg 内部 BBG code 不同 (详见
    # 历史调查文档 docs/archive/2026-07-02/raw_fills_null_investigation.md 第二节,
    # 已于 2026-08-12 随归档清理删除, 见 git 历史)。
    "MUMBAI": "Asia/Calcutta",
    "BSE": "Asia/Calcutta",
    "NSE": "Asia/Calcutta",
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

