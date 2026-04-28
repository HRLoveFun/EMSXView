"""
Market code derivation.

Project rule (locked in M1):
- `market_code` is the Bloomberg exchange code, **except** EUR-denominated
  tickers fold to `EU` regardless of exchange (project does not need
  per-bourse breakdown for the European zone in regime layer).
- `market_code` is the join key into `ref_market_mapping` and all
  `daily_*_regime` tables.

This is the SINGLE place to derive market_code; downstream code MUST
import from here, not reproduce the rule.
"""
from __future__ import annotations

from typing import Optional

# Bloomberg exchange codes that trade EUR-denominated equities. Used as a
# fallback when the source row has no Currency column (e.g. processed_fills.db).
# Keep in sync with ref_market_mapping rows where currency='EUR'.
EU_EXCHANGES: frozenset[str] = frozenset({
    "FP",  # Paris (Euronext)
    "GR",  # Xetra / Frankfurt
    "IM",  # Borsa Italiana (Milan)
    "SM",  # BME (Madrid)
    "FH",  # Helsinki
    "BB",  # Brussels
    "NA",  # Euronext Amsterdam
    "PL",  # Lisbon
    "AV",  # Vienna
    "GA",  # Athens
    "ID",  # Dublin
})

# Aliases for non-Bloomberg exchange labels found in processed_fills (e.g.
# legacy free-form text from manual imports). Map to canonical market_code.
EXCHANGE_ALIASES: dict[str, str] = {
    "MUMBAI": "IN",      # Bombay Stock Exchange / NSE → India
    "BOMBAY": "IN",
    "INDIA":  "IN",
    "NSE":    "IN",
    "BSE":    "IN",
}


def derive_market_code(exchange: Optional[str], currency: Optional[str] = None) -> Optional[str]:
    """Return regime-layer market_code for a fill row.

    Args:
        exchange: Bloomberg exchange code (e.g. 'US', 'HK', 'FP').
        currency: ISO currency (e.g. 'USD', 'EUR', 'HKD'); case-insensitive.
                  When None (e.g. processed_fills has no Currency column),
                  fall back to EU_EXCHANGES membership.

    Returns:
        Market code string, or None if exchange is missing/empty.
    """
    if currency and currency.strip().upper() == "EUR":
        return "EU"
    if not exchange or not exchange.strip():
        return None
    code = exchange.strip().upper()
    # Free-form aliases (e.g. 'MUMBAI' from manual imports).
    if code in EXCHANGE_ALIASES:
        return EXCHANGE_ALIASES[code]
    # Currency-less fallback: known EU bourses fold to 'EU'.
    if currency is None and code in EU_EXCHANGES:
        return "EU"
    return code

