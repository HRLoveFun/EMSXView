#!/usr/bin/env python3
"""
Diagnostic script for market data enrichment issues
Analyzes why %Change and ADV 5D may be empty for certain orders
"""

# Simulated order data
orders = [
    {"id": "4880699", "symbol": "UU/ LN Equity", "currency": "GBP"},
    {"id": "4880700", "symbol": "SVT LN Equity", "currency": "GBP"},
    {"id": "4880806", "symbol": "GLEN LN Equity", "currency": "GBP"},
]

# Simulated market data cache (may not have all tickers)
price_changes_cache = {
    "GLEN LN Equity": 2.5,  # Has data
    # "UU/ LN Equity" - missing
    # "SVT LN Equity" - missing
}

adv5d_cache = {
    "GLEN LN Equity": 15000000,  # Has data
    # "UU/ LN Equity" - missing
    # "SVT LN Equity" - missing
}

mkt_vwap_cache = {
    "GLEN LN Equity": 452.3,
}

subscribed_tickers = {"GLEN LN Equity"}  # Only subscribed to some tickers
failed_tickers = set()

print("=" * 70)
print("Market Data Enrichment Diagnostic")
print("=" * 70)

for order in orders:
    symbol = order["symbol"]
    print(f"\n{'='*70}")
    print(f"Order {order['id']}: {symbol}")
    print(f"{'='*70}")
    
    # Check subscription status
    is_subscribed = symbol in subscribed_tickers
    is_failed = symbol in failed_tickers
    has_price_change = symbol in price_changes_cache
    has_adv5d = symbol in adv5d_cache
    
    print(f"\n1. Subscription Status:")
    print(f"   Subscribed: {is_subscribed}")
    print(f"   Failed: {is_failed}")
    
    print(f"\n2. Cache Status:")
    print(f"   _price_changes.has('{symbol}'): {has_price_change}")
    if has_price_change:
        print(f"   _price_changes['{symbol}']: {price_changes_cache[symbol]}")
    else:
        print(f"   _price_changes['{symbol}']: NOT FOUND")
    
    print(f"   _adv5d.has('{symbol}'): {has_adv5d}")
    if has_adv5d:
        print(f"   _adv5d['{symbol}']: {adv5d_cache[symbol]}")
    else:
        print(f"   _adv5d['{symbol}']: NOT FOUND")
    
    print(f"\n3. Enrichment Result:")
    pct = price_changes_cache.get(symbol)
    adv = adv5d_cache.get(symbol)
    
    updates = {}
    if pct is not None:
        updates["pctChange"] = pct
    if adv is not None:
        updates["adv5d"] = adv
    
    print(f"   pctChange in updates: {'pctChange' in updates}")
    print(f"   adv5d in updates: {'adv5d' in updates}")
    
    if not updates:
        print(f"\n   *** PROBLEM: No market data enrichment for this order! ***")

print("\n" + "=" * 70)
print("Possible Causes:")
print("=" * 70)
print("""
1. Ticker Symbol Mismatch
   - EMSX returns: "UU/ LN Equity" (with slash)
   - Bloomberg mktdata may use: "UU LN Equity" (without slash)
   - The ticker format difference causes cache lookup to fail

2. Subscription Timing
   - Order added to cache before mktdata subscription updated
   - Subscription happens every loop iteration, but may miss new tickers

3. Bloomberg Field Availability
   - Some tickers may not have CHG_PCT_1D or VOLUME_AVG_5D fields
   - Especially for less liquid stocks or specific exchanges

4. Special Characters in Ticker
   - "/" in "UU/ LN Equity" may cause issues
   - Bloomberg may normalize the ticker differently
""")

print("=" * 70)
print("Recommendations:")
print("=" * 70)
print("""
1. Check backend logs for:
   - "Subscribing mktdata for X tickers" - see if ticker is in list
   - "[DEBUG 4880699]" and "[DEBUG 4880700]" output

2. Verify ticker format:
   - Compare EMSX ticker with Bloomberg mktdata topic format
   - May need to normalize tickers (remove special chars)

3. Check Bloomberg Terminal:
   - Look up "UU/ LN Equity" <GO>
   - Check if CHG_PCT_1D and VOLUME_AVG_5D fields exist
""")
