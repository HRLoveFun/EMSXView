"""Comprehensive FillFetch Test Suite"""
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import date
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent))

from src.secure_config import get_config_manager
from DataPipeline.ingestion.fill_fetch import FillFetch


def test_basic():
    """Test basic functionality."""
    print("\n=== TEST 1: Basic Functionality ===")
    temp_dir = tempfile.mkdtemp()
    try:
        fetcher = FillFetch(data_dir=f"{temp_dir}/fills", db_path=f"{temp_dir}/test.db")
        stats = fetcher.get_stats()
        assert stats['total_records'] == 0
        print(f"[OK] Stats: {stats['total_records']} records")
        fetcher.close()
        print("[PASS] Basic test")
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_hash():
    """Test hash computation."""
    print("\n=== TEST 2: Hash Computation ===")
    data = [{'fill_id': 1, 'price': 100.5}, {'fill_id': 2, 'price': 101.0}]
    h1 = compute_data_hash(data)
    h2 = compute_data_hash(data)
    assert h1 == h2 and len(h1) == 64
    print(f"[OK] Hash: {h1[:16]}...")
    print("[PASS] Hash test")
    return True


def test_dedup():
    """Test deduplication."""
    print("\n=== TEST 3: Deduplication ===")
    temp_dir = tempfile.mkdtemp()
    try:
        db = FillFetchDatabase(f"{temp_dir}/test.db")
        hash_val = "a" * 64
        db.add_fetch_record('2024-01-15', '00:00-23:59', 10, hash_val)
        is_dup = db.check_duplicate('2024-01-15', hash_val)
        assert is_dup == True
        print("[OK] Duplicate detected")
        db.close()
        print("[PASS] Deduplication test")
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_excel():
    """Test Excel export."""
    print("\n=== TEST 4: Excel Export ===")
    temp_dir = tempfile.mkdtemp()
    try:
        import pandas as pd
        data = [{'fill_id': 1, 'ticker': 'AAPL', 'price': 150.5, 'shares': 100}]
        file_path = Path(temp_dir) / "test.xlsx"
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine='openpyxl')
        assert file_path.exists()
        print(f"[OK] Excel saved: {file_path.stat().st_size} bytes")
        print("[PASS] Excel test")
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_config():
    """Test UUID configuration."""
    print("\n=== TEST 5: UUID Configuration ===")
    config = get_config_manager().get_uuid(allow_prompt=False, required=False)
    if config:
        print(f"[OK] UUID: {config.uuid} (from {config.description})")
    else:
        print("[WARN] No UUID configured")
    print("[PASS] Config test")
    return True


def test_regime():
    """Test regime layer end-to-end (uses mock fetcher, temp DBs)."""
    print("\n=== TEST 6: Regime Layer E2E ===")
    import unittest as _ut
    from CostView.tests.test_regime_e2e import RegimeE2ETest
    suite = _ut.TestLoader().loadTestsFromTestCase(RegimeE2ETest)
    runner = _ut.TextTestRunner(verbosity=0, stream=open(Path(tempfile.gettempdir()) / "regime_test.log", "w"))
    result = runner.run(suite)
    if result.wasSuccessful():
        print(f"[OK] {result.testsRun} regime sub-tests passed")
        print("[PASS] Regime test")
        return True
    print(f"[FAIL] regime: {len(result.failures)} failures, {len(result.errors)} errors")
    return False


def run_all():
    """Run all tests."""
    print("=" * 50)
    print("FillFetch Comprehensive Test Suite")
    print("=" * 50)
    
    tests = [test_basic, test_hash, test_dedup, test_excel, test_config, test_regime]
    passed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
    
    print("\n" + "=" * 50)
    print(f"Results: {passed}/{len(tests)} tests passed")
    print("=" * 50)


if __name__ == '__main__':
    run_all()
