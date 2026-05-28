"""
Pure utility functions extracted from bloomberg_adapter.py.

These are self-contained helpers with no dependency on BloombergEMSXService
instance state. They operate solely on Bloomberg message objects and/or
simple input parameters.
"""
from __future__ import annotations

from typing import Optional


# ── Message field parsers (no self dependency) ──────────────────────────

def msg_safe_int(msg, name: str, default: int = 0) -> int:
    """Safely read an integer field from a Bloomberg message element."""
    try:
        if msg.hasElement(name):
            return msg.getElementAsInteger(name)
    except Exception:
        pass
    return default


def msg_safe_float(msg, name: str, default: float = 0.0) -> float:
    """Safely read a float field from a Bloomberg message element."""
    try:
        if msg.hasElement(name):
            return msg.getElementAsFloat(name)
    except Exception:
        pass
    return default


def msg_safe_str(msg, name: str, default: str = "") -> str:
    """Safely read a string field from a Bloomberg message element."""
    try:
        if msg.hasElement(name):
            return msg.getElementAsString(name)
    except Exception:
        pass
    return default


# ── Strategy time formatting ───────────────────────────────────────────

def format_strategy_time(raw: int) -> str:
    """Convert Bloomberg strategy time integer to HH:MM string.

    Bloomberg encodes strategy start/end times as integers in HHMM format
    (e.g. 930 = 09:30, 1600 = 16:00) or as seconds from midnight.
    Returns empty string for 0 (unset).
    """
    if not raw or raw <= 0:
        return ""
    # If value looks like seconds from midnight (> 2400), convert
    if raw > 2400:
        h = raw // 3600
        m = (raw % 3600) // 60
    else:
        # HHMM format
        h = raw // 100
        m = raw % 100
    return f"{h:02d}:{m:02d}"


# ── Currency & exchange derivation ─────────────────────────────────────

# Mapping of Bloomberg exchange suffixes to trading currencies
_EXCHANGE_CURRENCY_MAP = {
    "US": "USD", "UN": "USD", "UQ": "USD", "UW": "USD", "UA": "USD", "UP": "USD",
    "CT": "USD", "UF": "USD",
    "CN": "CAD", "CF": "CAD",
    "LN": "GBP", "LI": "GBP",
    "JP": "JPY", "JT": "JPY",
    "HK": "HKD",
    "CH": "CNY", "CS": "CNY", "CG": "CNY", "CI": "CNY", "C1": "CNY", "C2": "CNY",
    "SS": "CNY", "SZ": "CNY",
    "GR": "EUR", "GY": "EUR", "GF": "EUR",
    "FP": "EUR", "PA": "EUR",
    "IM": "EUR", "NA": "EUR", "SM": "EUR", "BB": "EUR",
    "SQ": "EUR", "PL": "EUR", "ID": "EUR", "GA": "EUR",
    "AU": "AUD", "AT": "AUD",
    "SP": "SGD", "SI": "SGD",
    "KS": "KRW", "KQ": "KRW",
    "TT": "TWD",
    "TB": "THB",
    "IJ": "IDR",
    "MK": "MYR",
    "PM": "PHP",
    "IN": "INR", "IB": "INR", "IS": "INR",
    "BZ": "BRL",
    "MM": "MXN",
    "NZ": "NZD",
    "ST": "SEK", "NO": "NOK", "DC": "DKK", "FH": "EUR",
    "SW": "CHF", "SE": "CHF",
    "SJ": "ZAR",
    "AB": "AED",
}


def derive_currency(currency_pair: str, ticker: str) -> str:
    """Derive the **trading currency** of the security.

    EMSX_CURRENCY_PAIR is unreliable for this purpose because:
      - It may return the settlement/user currency ("USD") for non-USD securities.
      - It may return a 6-char pair code ("HKDUSD") which is not a valid 3-char ccy.
    Therefore we **prioritise the ticker exchange suffix** (always reliable for
    exchange-listed instruments) and only fall back to EMSX_CURRENCY_PAIR when
    the ticker cannot be resolved.

    Priority:
      1. Ticker exchange suffix → _EXCHANGE_CURRENCY_MAP  (most reliable)
      2. EMSX_CURRENCY_PAIR parsed intelligently               (fallback)
      3. Empty string                                           (last resort)
    """
    # ── Step 1: Ticker exchange suffix (most reliable) ──────────────
    ticker_ccy = ""
    parts = ticker.strip().split() if ticker else []
    if len(parts) >= 2:
        asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
        exch_code = parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
        ticker_ccy = _EXCHANGE_CURRENCY_MAP.get(exch_code, "")

    if ticker_ccy:
        return ticker_ccy

    # ── Step 2: Parse EMSX_CURRENCY_PAIR ────────────────────────────
    if currency_pair:
        cp = currency_pair.strip()
        # Handle 6-char pair codes like "HKDUSD", "JPYUSD" → extract first 3 chars
        if len(cp) == 6 and cp[3:].upper() == "USD":
            return cp[:3].upper()            # "HKDUSD" → "HKD"
        if len(cp) == 6 and cp[:3].upper() == "USD":
            return cp[3:].upper()            # "USDHKD" → "HKD"
        # Handle slash-separated pairs
        if "/" in cp:
            parts_pair = [p.strip() for p in cp.split("/")]
            # Return the non-USD side, preferring first token
            for p in parts_pair:
                if p.upper() != "USD" and len(p) == 3:
                    return p.upper()
            # Both sides might be the same or both USD — return first
            return parts_pair[0].upper() if parts_pair[0] else ""
        # Plain 3-char code (e.g. "HKD", "JPY", "USD")
        if len(cp) <= 3:
            return cp.upper()

    return ""


def derive_exchange(ticker: str) -> str:
    """Derive exchange code from Bloomberg ticker suffix (e.g., '7203 JP Equity' → 'JP')."""
    parts = ticker.strip().split() if ticker else []
    if len(parts) >= 2:
        asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
        return parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
    return ""


# ── Order type checks ─────────────────────────────────────────────────

def order_type_uses_limit_price(order_type: str) -> bool:
    """Return True if the order type requires a limit price."""
    return order_type in {"LMT", "STPLMT"}


def order_type_uses_stop_price(order_type: str) -> bool:
    """Return True if the order type requires a stop price."""
    return order_type in {"STP", "STPLMT"}
