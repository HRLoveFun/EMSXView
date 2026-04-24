import sqlite3
for dbf, tbl, col in [
    ("CostView/data/processed_fills.db", "processed_fills", "order_as_of_date"),
    ("CostView/data/fill_bdib.db", "fill_bdib", "order_as_of_date"),
    ("CostView/data/raw_bdib.db", "raw_bdib", "order_as_of_date"),
]:
    c = sqlite3.connect(f"file:{dbf}?mode=ro", uri=True)
    print(f"=== {tbl} / {col} ===")
    try:
        print("  Top 5 distinct (DESC):")
        for r in c.execute(f"SELECT DISTINCT {col} FROM {tbl} WHERE {col} > '' ORDER BY {col} DESC LIMIT 5"):
            print("   ", r)
    except Exception as e:
        print(f"  ERR: {e}")
    c.close()
