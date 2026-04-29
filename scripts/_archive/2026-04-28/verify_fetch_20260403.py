"""
Fetch & Compare Script — Re-fetch a specific date from Bloomberg EMSX
and compare against existing raw_fills.db to detect data gaps.

Usage:
    python scripts/verify_fetch_20260403.py

This script does NOT write to the database. It only fetches into memory
and compares.
"""

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# Ensure CostView is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "CostView"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    target_date = date(2026, 4, 3)   # Can be changed via --date arg
    tolerance = 0.01

    # ── Parse optional CLI args ───────────────────────────────────────
    if len(sys.argv) > 1 and sys.argv[1] == "--date" and len(sys.argv) > 2:
        target_date = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()

    ds = target_date.strftime("%Y%m%d")
    print("=" * 72)
    print(f"  FETCH & VERIFY: {ds}")
    print("  Re-fetching from Bloomberg EMSX API (in-memory, NO DB write)")
    print("=" * 72)

    # ── Step 1: Read existing DB snapshot ─────────────────────────────
    import sqlite3
    db_path = Path(__file__).resolve().parents[1] / "CostView" / "data" / "raw_fills.db"
    conn = sqlite3.connect(str(db_path))
    try:
        db_df = pd.read_sql_query(
            """SELECT OrderId, FillId, ExecType, FillPrice, FillShares,
                      Amount, RouteId, DateTimeOfFill,
                      source_date, fetched_at
               FROM raw_fills WHERE source_date = ?""",
            conn, params=[ds],
        )
        # Also read full columns for detailed diff
        db_full = pd.read_sql_query(
            f"SELECT * FROM raw_fills WHERE source_date = ?", conn, params=[ds]
        )
    finally:
        conn.close()

    print(f"\n[DB SNAPSHOT] source_date={ds}")
    print(f"  Rows:       {len(db_df)}")
    print(f"  Orders:     {db_df['OrderId'].nunique()}")
    print(f"  Fills:      {db_df['FillId'].nunique()} unique FillIds")
    print(f"  Time range: {db_df['DateTimeOfFill'].min()} ~ {db_df['DateTimeOfFill'].max()}")
    print(f"  ExecType:   {dict(db_df['ExecType'].value_counts())}")

    # ── Step 2: Fetch fresh from Bloomberg ────────────────────────────
    from src.fill_fetch import BloombergFillFetcher

    from_dt = datetime.combine(target_date, datetime.min.time())
    to_dt = datetime.combine(target_date, datetime.max.time().replace(microsecond=0))

    print(f"\n[BLOOMBERG FETCH]")
    print(f"  Range:  {from_dt.isoformat()} ~ {to_dt.isoformat()}")
    print("  Connecting...")

    fresh_fills = []
    try:
        with BloombergFillFetcher() as client:
            fresh_fills = client.fetch_fills(from_dt, to_dt)
    except Exception as e:
        print(f"  ERROR: Failed to connect to Bloomberg: {e}")
        print("  Is Bloomberg Desktop running? Check BLPAPI connection.")
        return

    if not fresh_fills:
        print("  No fills returned from Bloomberg.")
        return

    api_df = pd.DataFrame(fresh_fills)

    print(f"  Fetched:   {len(api_df)} rows")
    print(f"  Orders:    {api_df['OrderId'].nunique()}")
    print(f"  FillIds:   {api_df['FillId'].nunique()}")
    print(f"  Time range: {api_df['DateTimeOfFill'].min()} ~ {api_df['DateTimeOfFill'].max()}")

    # ── Step 3: Compare ──────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  COMPARISON: DB vs Fresh Bloomberg Data")
    print("=" * 72)

    # 3a: Row-level count
    print(f"\n{'Metric':<35} {'DB':>10} {'Fresh':>10} {'Delta':>10} {'Status'}")
    print("-" * 75)
    print(f"{'Total rows':<35} {len(db_df):>10} {len(api_df):>10} "
          f"{len(api_df)-len(db_df):>+10}", end="")
    print("  ** MISMATCH **" if len(db_df) != len(api_df) else "")

    db_orders = set(db_df["OrderId"].astype(str).unique())
    api_orders = set(api_df["OrderId"].astype(str).unique())
    print(f"{'Unique OrderIds':<35} {len(db_orders):>10} {len(api_orders):>10} "
          f"{len(api_orders)-len(db_orders):>+10}", end="")
    print("  ** MISMATCH **" if db_orders != api_orders else "")

    db_fillids = set(db_df["FillId"].astype(str).unique())
    api_fillids = set(api_df["FillId"].astype(str).unique())
    missing_in_db = api_fillids - db_fillids
    extra_in_db = db_fillids - api_fillids
    print(f"{'Unique FillIds':<35} {len(db_fillids):>10} {len(api_fillids):>10} "
          f"{len(api_fillids)-len(db_fillids):>+10}",
          f"  (DB missing {len(missing_in_db)}, DB extra {len(extra_in_db)})")

    # 3b: Order-level detail
    if db_orders != api_orders:
        only_fresh = api_orders - db_orders
        only_db = db_orders - api_orders
        if only_fresh:
            print(f"\n  >>> Orders in Fresh but MISSING from DB ({len(only_fresh)}):")
            for oid in sorted(only_fresh):
                sub = api_df[api_df["OrderId"] == int(oid)]
                print(f"      OrderId={oid}: {len(sub)} rows, Amount={sub['Amount'].iloc[0]}")
        if only_db:
            print(f"\n  >>> Orders in DB but NOT in Fresh ({len(only_db)}):")
            for oid in sorted(only_db):
                sub = db_df[db_df["OrderId"].astype(str) == oid]
                print(f"      OrderId={oid}: {len(sub)} rows")

    # 3c: Per-order FillShare validation on BOTH datasets
    print(f"\n--- Per-Order SUM(FillShares) vs Amount ---")
    print(f"{'OrderId':<12} {'DB_rows':>8} {'Fresh_rows':>10} {'DB_sumFS':>10} "
          f"{'Fresh_sumFS':>12} {'Amount':>10} {'DB_Diff':>9} {'Fresh_Diff':>11}")

    all_orders = sorted(db_orders | api_orders)
    discrepancies = []

    for oid in all_orders:
        db_sub = db_df[db_df["OrderId"].astype(str) == str(oid)]
        api_sub = api_df[api_df["OrderId"] == int(oid)] if int(oid) in api_df["OrderId"].values else pd.DataFrame()

        amount_val = None
        if not db_sub.empty:
            amount_val = float(db_sub["Amount"].iloc[0])
        elif not api_sub.empty:
            amount_val = float(api_sub["Amount"].iloc[0])

        db_sum = float(db_sub["FillShares"].astype(float).sum()) if not db_sub.empty else 0
        fs_sum = float(api_sub["FillShares"].sum()) if not api_sub.empty else 0

        db_diff = round(db_sum - (amount_val or 0), 2)
        fs_diff = round(fs_sum - (amount_val or 0), 2)

        flag = ""
        if abs(db_diff) > tolerance or abs(fs_diff) > tolerance:
            flag = " *"
        if db_sum != fs_sum or len(db_sub) != len(api_sub):
            flag = " ***"
            discrepancies.append({
                "OrderId": oid,
                "DB_rows": len(db_sub),
                "Fresh_rows": len(api_sub),
                "DB_SumFillShares": db_sum,
                "Fresh_SumFillShares": fs_sum,
                "Diff": fs_sum - db_sum,
            })

        print(
            f"{str(oid):<12} {len(db_sub):>8} {len(api_sub):>10} "
            f"{db_sum:>10.1f} {fs_sum:>12.1f} {(amount_val or 0):>10.0f} "
            f"{db_diff:>+9.1f} {fs_diff:>+11.1f}{flag}"
        )

    # 3d: Row-by-row diff for specific order of interest (5159147)
    target_oid = "5159147"
    print(f"\n--- Detail: OrderId={target_oid} ---")
    db_oid = db_df[db_df["OrderId"].astype(str) == target_oid].copy()
    api_oid = api_df[api_df["OrderId"] == int(target_oid)].copy()

    print(f"  DB rows:    {len(db_oid)}")
    print(f"  Fresh rows: {len(api_oid)}")

    db_fs = set(tuple(z) for z in db_oid[["FillId", "FillPrice", "FillShares"]].dropna().values.tolist())
    api_fs = set(tuple(z) for z in api_oid[["FillId", "FillPrice", "FillShares"]].dropna().values.tolist())

    only_api = api_fs - db_fs
    only_db = db_fs - api_fs

    if only_api:
        print(f"\n  >>> Rows in Fresh but MISSING from DB ({len(only_api)}):")
        sorted_missing = sorted(list(only_api), key=lambda x: x[0])
        for fid, fp, fs in sorted_missing[:30]:
            print(f"      FillId={fid:>4}, Price={fp:>10.1f}, Shares={fs:>6.1f}")
        if len(sorted_missing) > 30:
            print(f"      ... and {len(sorted_missing) - 30} more")

    if only_db:
        print(f"\n  >>> Rows in DB but NOT in Fresh ({len(only_db)}):")
        sorted_extra = sorted(list(only_db), key=lambda x: x[0])
        for fid, fp, fs in sorted_extra[:20]:
            print(f"      FillId={fid:>4}, Price={fp:>10.1f}, Shares={fs:>6.1f}")

    if not only_api and not only_db:
        print("  >>> ROWS ARE IDENTICAL (no missing/extra)")

    # Summary
    print("\n" + "=" * 72)
    if discrepancies:
        print(f"  RESULT: {len(discrepancies)} order(s) have DATA DIFFERENCES between DB and Fresh fetch!")
        print(f"  The DB may be stale or the Bloomberg data has been updated since last fetch.")
    elif len(db_df) == len(api_df) and db_orders == api_orders:
        print("  RESULT: DB and Fresh data are CONSISTENT. No gaps detected.")
    else:
        print("  RESULT: Counts match per-order but some FillIds differ (possible late corrections).")
    print("=" * 72)


if __name__ == "__main__":
    main()
