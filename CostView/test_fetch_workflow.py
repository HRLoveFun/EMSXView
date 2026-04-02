"""FillFetch Workflow Test - Simulates actual fetch process"""
import sys
import tempfile
import shutil
from pathlib import Path
from datetime import date
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).parent))

from src.fill_fetch import FillFetch
from src.database import compute_data_hash
import pandas as pd


@dataclass
class MockFill:
    fill_id: int
    order_id: int
    date_time_of_fill: str
    fill_price: float
    fill_shares: float
    ticker: str = ""
    side: str = ""


def simulate_fetch(target_date: date, uuid: int):
    date_str = target_date.strftime('%Y-%m-%d')
    return [
        MockFill(1, 100, f"{date_str}T10:30:00.000+00:00", 150.50, 100, "AAPL", "BUY"),
        MockFill(2, 100, f"{date_str}T10:31:15.000+00:00", 150.55, 50, "AAPL", "BUY"),
        MockFill(3, 101, f"{date_str}T11:00:00.000+00:00", 250.00, 200, "MSFT", "BUY"),
    ]


def test_workflow():
    print("=" * 60)
    print("FillFetch Workflow Test")
    print("=" * 60)
    
    temp_dir = tempfile.mkdtemp()
    try:
        fetcher = FillFetch(data_dir=f"{temp_dir}/fills", db_path=f"{temp_dir}/history.db")
        target_date = date(2024, 1, 15)
        uuid = 30937014
        
        print(f"\n[SETUP] Date: {target_date}, UUID: {uuid}")
        
        # First fetch
        print("\n[FETCH 1] First fetch...")
        fills = simulate_fetch(target_date, uuid)
        data_dicts = [asdict(f) for f in fills]
        hash_val = compute_data_hash(data_dicts)
        print(f"  Got {len(fills)} fills, hash: {hash_val[:16]}...")
        
        is_dup = fetcher.db.check_duplicate(target_date.strftime('%Y-%m-%d'), hash_val)
        print(f"  Is duplicate: {is_dup}")
        
        if not is_dup:
            # Save to Excel
            file_path = Path(temp_dir) / "fills" / f"fills_{target_date}_{uuid}.xlsx"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(data_dicts).to_excel(file_path, index=False, engine='openpyxl')
            print(f"  Saved Excel: {file_path.stat().st_size} bytes")
            
            # Record to DB
            fetcher.db.add_fetch_record(
                target_date.strftime('%Y-%m-%d'), '00:00-23:59', len(fills), hash_val, str(file_path)
            )
            print("  Recorded to database")
        
        stats = fetcher.get_stats()
        print(f"\n[VERIFY 1] Records: {stats['total_records']}, Rows: {stats['total_rows_fetched']}")
        assert stats['total_records'] == 1
        
        # Second fetch (duplicate)
        print("\n[FETCH 2] Second fetch (should be duplicate)...")
        fills2 = simulate_fetch(target_date, uuid)
        hash_val2 = compute_data_hash([asdict(f) for f in fills2])
        is_dup2 = fetcher.db.check_duplicate(target_date.strftime('%Y-%m-%d'), hash_val2)
        print(f"  Is duplicate: {is_dup2}")
        
        if is_dup2:
            print("  [OK] Duplicate detected - skipping save")
        
        stats2 = fetcher.get_stats()
        print(f"\n[VERIFY 2] Records: {stats2['total_records']} (should still be 1)")
        assert stats2['total_records'] == 1
        
        # Different date
        print("\n[FETCH 3] Different date (2024-01-16)...")
        date2 = date(2024, 1, 16)
        fills3 = simulate_fetch(date2, uuid)
        hash_val3 = compute_data_hash([asdict(f) for f in fills3])
        is_dup3 = fetcher.db.check_duplicate(date2.strftime('%Y-%m-%d'), hash_val3)
        print(f"  Is duplicate: {is_dup3}")
        
        if not is_dup3:
            fetcher.db.add_fetch_record(date2.strftime('%Y-%m-%d'), '00:00-23:59', len(fills3), hash_val3)
            print("  [OK] New date - saved to database")
        
        stats3 = fetcher.get_stats()
        print(f"\n[VERIFY 3] Records: {stats3['total_records']} (should be 2)")
        assert stats3['total_records'] == 2
        
        fetcher.close()
        print("\n" + "=" * 60)
        print("ALL WORKFLOW TESTS PASSED!")
        print("=" * 60)
        
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    test_workflow()
