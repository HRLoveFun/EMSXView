"""Quick test for _derive_exchange logic."""

def _derive_exchange(ticker: str) -> str:
    parts = ticker.strip().split() if ticker else []
    if len(parts) >= 2:
        asset_types = ("EQUITY", "GOVT", "CORP", "COMDTY", "INDEX", "CURNCY", "PREF", "MTGE")
        return parts[-2].upper() if parts[-1].upper() in asset_types else parts[-1].upper()
    return ""

tests = [
    ("7203 JP Equity", "JP"),
    ("AAPL US Equity", "US"),
    ("9988 HK Equity", "HK"),
    ("VOD LN Equity", "LN"),
    ("7267 JT Equity", "JT"),
    ("", ""),
    ("AAPL", ""),
    ("SPX Index", "SPX"),   # Index type
    ("USD Curncy", "USD"),  # Currency type
]

all_pass = True
for ticker, expected in tests:
    result = _derive_exchange(ticker)
    status = "PASS" if result == expected else "FAIL"
    if result != expected:
        all_pass = False
    print(f"{status}: _derive_exchange('{ticker}') = '{result}' (expected '{expected}')")

print(f"\n{'All tests passed!' if all_pass else 'Some tests FAILED!'}")
