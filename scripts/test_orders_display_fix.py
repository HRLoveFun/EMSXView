#!/usr/bin/env python3
"""
Test script: Verify Orders Display Fix

Usage:
    python scripts/test_orders_display_fix.py
"""

import sys
import os


def test_init_paint_timeout():
    """Test 1: Verify INIT_PAINT timeout increased"""
    print("Test 1: INIT_PAINT timeout increased to 30s")
    print("-" * 50)

    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'ExecutionView', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'for _ in range(60):' in content and '# INCREASED: From 30 iterations' in content:
        print("[PASS] INIT_PAINT timeout increased to 60 iterations (30s)")
        return True
    else:
        print("[FAIL] INIT_PAINT timeout not updated")
        return False


def test_status_api():
    """Test 2: Verify order status API endpoint"""
    print("\nTest 2: Order status API endpoint")
    print("-" * 50)

    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'ExecutionView', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = [
        ('Status endpoint defined', '@app.get("/api/orders/status"'),
        ('Returns init_paint_done', 'init_paint_done'),
        ('Returns order_count', 'order_count'),
        ('Returns is_connected', 'is_connected'),
    ]

    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print(f"[PASS] {name}")
        else:
            print(f"[FAIL] {name}")
            all_found = False

    return all_found


def test_frontend_api():
    """Test 3: Verify frontend API service method"""
    print("\nTest 3: Frontend API service method")
    print("-" * 50)

    api_ts_path = os.path.join(os.path.dirname(__file__), '..', 'ExecutionView', 'frontend', 'src', 'services', 'api.ts')
    with open(api_ts_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = [
        ('getOrdersStatus method', 'async getOrdersStatus'),
        ('Returns init_paint_done', 'init_paint_done: boolean'),
        ('Returns order_count', 'order_count: number'),
    ]

    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print(f"[PASS] {name}")
        else:
            print(f"[FAIL] {name}")
            all_found = False

    return all_found


def test_frontend_filter_indicator():
    """Test 4: Verify frontend filter indicator"""
    print("\nTest 4: Frontend filter indicator")
    print("-" * 50)

    order_table_path = os.path.join(os.path.dirname(__file__), '..', 'ExecutionView', 'frontend', 'src', 'sections', 'OrderTable.tsx')
    with open(order_table_path, 'r', encoding='utf-8') as f:
        content = f.read()

    checks = [
        ('activeFilterCount computed', 'const activeFilterCount'),
        ('Order count display', 'Showing'),
        ('Filter count display', 'activeFilterCount > 0'),
        ('Debug logging', '[OrderTable]'),
        ('useEffect import', 'useEffect'),
    ]

    all_found = True
    for name, pattern in checks:
        if pattern in content:
            print(f"[PASS] {name}")
        else:
            print(f"[FAIL] {name}")
            all_found = False

    return all_found


def test_trailing_orders_wait():
    """Test 5: Verify trailing orders wait logic"""
    print("\nTest 5: Trailing orders wait logic")
    print("-" * 50)

    main_py_path = os.path.join(os.path.dirname(__file__), '..', 'ExecutionView', 'backend', 'api', 'main.py')
    with open(main_py_path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'await asyncio.sleep(2.0)' in content and 'Orders arriving:' in content:
        print("[PASS] Trailing orders wait logic implemented")
        return True
    else:
        print("[FAIL] Trailing orders wait logic not found")
        return False


def main():
    print("=" * 60)
    print("Orders Display Fix Verification Tests")
    print("=" * 60)

    results = [
        test_init_paint_timeout(),
        test_status_api(),
        test_frontend_api(),
        test_frontend_filter_indicator(),
        test_trailing_orders_wait(),
    ]

    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")

    if passed == total:
        print("[SUCCESS] All tests passed! Fix is properly applied.")
        return 0
    else:
        print("[ERROR] Some tests failed. Please review the changes.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
