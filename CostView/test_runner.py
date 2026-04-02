"""Test runner for FillFetch"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.fill_fetch import FillFetch
from src.secure_config import get_config_manager

def test_basic():
    print("=" * 50)
    print("FillFetch Basic Test")
    print("=" * 50)
    
    # Test 1: Config validation
    print("\n1. Testing configuration...")
    config = get_config_manager().get_uuid(allow_prompt=False, required=False)
    if config:
        print(f"   [OK] UUID loaded: {config.uuid}")
        print(f"   [OK] Source: {config.description}")
    else:
        print("   [WARN] No UUID configured")
    
    # Test 2: Initialize FillFetch
    print("\n2. Testing FillFetch initialization...")
    fetcher = FillFetch()
    print("   [OK] FillFetch initialized")
    
    # Test 3: Get stats
    print("\n3. Testing get_stats...")
    stats = fetcher.get_stats()
    print(f"   [OK] Total records: {stats['total_records']}")
    print(f"   [OK] Database path: {stats['database_path']}")
    
    # Test 4: Get history
    print("\n4. Testing get_history...")
    history = fetcher.get_history()
    print(f"   [OK] History entries: {len(history)}")
    
    fetcher.close()
    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)

if __name__ == '__main__':
    test_basic()
