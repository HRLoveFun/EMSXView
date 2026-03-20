#!/usr/bin/env python3
"""
Diagnostic script: Check order 4880806 (GLEN LN Equity) calculation logic
"""

# Simulate order data
order = {
    "id": "4880806",
    "symbol": "GLEN LN Equity",
    "quantity": 1000,  # Assumed quantity
    "currency": "GBP",  # From _derive_currency
    "mktVwap": None,  # From original order
    "lastPrice": None,
    "avgPrice": 450.5,  # Assumed avg price
    "price": 450.0,  # Assumed limit price
}

# Simulate cache data
mkt_vwap_cache = {"GLEN LN Equity": 452.3}  # From _mkt_vwap cache
price_changes_cache = {}
adv5d_cache = {}
fx_rates_cache = {"GBP": 1.25}  # Assumed GBP rate
ticker_currencies_cache = {}  # From _ticker_currencies

print("=" * 60)
print("Diagnose Order 4880806 (GLEN LN Equity)")
print("=" * 60)

# Step 1: Get enriched mktVwap
vwap = mkt_vwap_cache.get(order["symbol"])
print(f"\n1. VWAP Retrieval:")
print(f"   vwap from cache = {vwap}")
print(f"   o.mktVwap (original) = {order['mktVwap']}")
effective_vwap = vwap if vwap is not None else order["mktVwap"]
print(f"   effective_vwap = {effective_vwap}")

# Step 2: Get currency
auth_ccy = ticker_currencies_cache.get(order["symbol"]) or order["currency"] or ""
print(f"\n2. Currency Resolution:")
print(f"   auth_ccy = '{auth_ccy}'")

# Step 3: Get FX rate
fx_rate = None
if auth_ccy:
    if auth_ccy == "USD":
        fx_rate = 1.0
    else:
        fx_rate = fx_rates_cache.get(auth_ccy)
print(f"\n3. FX Rate:")
print(f"   fx_rate = {fx_rate}")
print(f"   Available FX rates: {fx_rates_cache}")

# Step 4: Calculate best price
best_price = (
    effective_vwap if (effective_vwap and effective_vwap > 0) else
    order["lastPrice"] if (order["lastPrice"] and order["lastPrice"] > 0) else
    order["avgPrice"] if (order["avgPrice"] and order["avgPrice"] > 0) else
    order["price"] if (order["price"] and order["price"] > 0) else
    None
)
print(f"\n4. Best Price Calculation:")
print(f"   effective_vwap = {effective_vwap} (valid: {effective_vwap and effective_vwap > 0})")
print(f"   lastPrice = {order['lastPrice']}")
print(f"   avgPrice = {order['avgPrice']}")
print(f"   price = {order['price']}")
print(f"   -> best_price = {best_price}")

# Step 5: Calculate dollarValueUsd
print(f"\n5. USD Value Calculation:")
print(f"   best_price = {best_price}")
print(f"   quantity = {order['quantity']}")
print(f"   auth_ccy = '{auth_ccy}'")
print(f"   fx_rate = {fx_rate}")

dollar_value = None
if best_price and order["quantity"] > 0:
    if auth_ccy == "USD" or not auth_ccy:
        dollar_value = round(best_price * order["quantity"], 0)
        print(f"   -> USD calc: {best_price} * {order['quantity']} = {dollar_value}")
    elif fx_rate is not None and fx_rate > 0:
        if auth_ccy in ("GBP", "ZAR"):
            dollar_value = round(best_price * order["quantity"] * fx_rate / 100, 0)
            print(f"   -> GBP/ZAR calc: {best_price} * {order['quantity']} * {fx_rate} / 100 = {dollar_value}")
        else:
            dollar_value = round(best_price * order["quantity"] * fx_rate, 0)
            print(f"   -> Non-USD calc: {best_price} * {order['quantity']} * {fx_rate} = {dollar_value}")
    else:
        print(f"   -> NO dollarValueUsd: fx_rate is None for non-USD currency '{auth_ccy}'")
else:
    print(f"   -> NO dollarValueUsd: best_price={best_price}, quantity={order['quantity']}")

print("\n" + "=" * 60)
print("Potential Issues Analysis:")
print("=" * 60)

problems = []

if vwap is None and order["mktVwap"] is None:
    problems.append("- mktVwap is empty (both cache and original order)")
    
if not auth_ccy:
    problems.append("- Currency resolution failed (auth_ccy is empty)")
    
if auth_ccy and auth_ccy != "USD" and fx_rate is None:
    problems.append(f"- FX rate missing: {auth_ccy} not in fx_rates cache")
    
if best_price is None:
    problems.append("- Best price calculation failed (all price sources are empty)")

if problems:
    for p in problems:
        print(p)
else:
    print("- All input data is valid, dollarValueUsd should be calculated")
    
print("\n" + "=" * 60)
print("Recommendations:")
print("=" * 60)
print("1. Check backend logs for 'DEBUG 4880806' output")
print("2. Check if _mkt_vwap cache contains 'GLEN LN Equity'")
print("3. Check if _fx_rates cache contains 'GBP'")
print("4. Check if order's original currency field is correct")
print("5. Run: docker compose logs -f backend | findstr DEBUG")
