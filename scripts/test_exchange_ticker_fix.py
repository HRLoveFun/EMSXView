#!/usr/bin/env python3
"""
Test script: Verify Exchange/Ticker field fix

Usage:
    python scripts/test_exchange_ticker_fix.py
"""

import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Execution', 'backend', 'api'))

def test_order_model():
    """Test 1: Verify Order model has exchange as string type"""
    print("Test 1: Order model exchange field type")
    print("-" * 50)
    
    # Read the main.py file and check the Order model
    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'Execution', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for exchange: str = "" in Order model
    if 'exchange: str = ""' in content or "exchange: str = ''" in content:
        print("[PASS] Order.exchange is defined as str with default empty string")
        return True
    else:
        print("[FAIL] Order.exchange is still Optional[str]")
        return False


def test_route_model():
    """Test 2: Verify Route model has enrichment fields"""
    print("\nTest 2: Route model enrichment fields")
    print("-" * 50)
    
    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'Execution', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_fields = ['ticker: str', 'side: str', 'portfolio: str', 
                      'trader: str', 'traderUuid: int', 'currency: str', 'exchange: str']
    
    all_found = True
    for field in required_fields:
        if field in content:
            print("[PASS] Found field: {}".format(field))
        else:
            print("[FAIL] Missing field: {}".format(field))
            all_found = False
    
    return all_found


def test_enrichment_logic():
    """Test 3: Verify enhanced enrichment logic"""
    print("\nTest 3: Route enrichment logic")
    print("-" * 50)
    
    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'Execution', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ("Use cached values on route if available", "Use cached values on route if available"),
        ("Delayed enrichment method", "_enrich_routes_with_new_order"),
        ("Preserve enrichment fields in merge", "enrichment_fields = ["),
        ("Enrichment fields preservation", 'for ef in enrichment_fields:'),
    ]
    
    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print("[PASS] {}".format(name))
        else:
            print("[FAIL] {}".format(name))
            all_found = False
    
    return all_found


def test_frontend_defaults():
    """Test 4: Verify frontend default value handling"""
    print("\nTest 4: Frontend default value handling")
    print("-" * 50)
    
    route_table_path = os.path.join(os.path.dirname(__file__), '..', 'Execution', 'frontend', 'src', 'sections', 'RouteTable.tsx')
    with open(route_table_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ("Ticker display with default", "route.ticker || '-'"),
        ("Exchange display with default", "route.exchange || '-'"),
        ("Ticker filter with default", "(r.ticker || '')"),
    ]
    
    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print("[PASS] {}".format(name))
        else:
            print("[FAIL] {}".format(name))
            all_found = False
    
    return all_found


def test_logging():
    """Test 5: Verify logging statements"""
    print("\nTest 5: Logging statements")
    print("-" * 50)
    
    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'Execution', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ("Enrich route log", "Enrich route {r.id}:"),
        ("Delayed enrichment log", "Delayed enrichment for route"),
        ("Enriched count log", "Enriched {enriched_count} routes"),
    ]
    
    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print("[PASS] {}".format(name))
        else:
            print("[FAIL] {}".format(name))
            all_found = False
    
    return all_found


def main():
    print("=" * 60)
    print("Exchange/Ticker Field Fix Verification Tests")
    print("=" * 60)
    
    results = [
        test_order_model(),
        test_route_model(),
        test_enrichment_logic(),
        test_frontend_defaults(),
        test_logging(),
    ]
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print("Tests passed: {}/{}".format(passed, total))
    
    if passed == total:
        print("[SUCCESS] All tests passed! Fix is properly applied.")
        return 0
    else:
        print("[ERROR] Some tests failed. Please review the changes.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
