"""检查 tca_route_summary 当前状态（行数、列、样本）。"""
import sqlite3
import sys
from pathlib import Path

db = Path(r"C:\Users\hrchen\Documents\EMSXView\CostView\data\fill_bdib.db")
if not db.exists():
    print(f"DB not found: {db}")
    sys.exit(1)

conn = sqlite3.connect(str(db))
c = conn.cursor()

t = c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='tca_route_summary'"
).fetchone()
print(f"table_exists: {bool(t)}")

if not t:
    conn.close()
    sys.exit(0)

cols = [d[0] for d in c.execute("SELECT * FROM tca_route_summary LIMIT 1").description]
print(f"columns({len(cols)}): {cols}")
print(f"fill_count column present: {'fill_count' in cols}")

count = c.execute("SELECT COUNT(*) FROM tca_route_summary").fetchone()[0]
print(f"row_count: {count}")

if count > 0:
    dates = c.execute(
        "SELECT DISTINCT order_as_of_date FROM tca_route_summary ORDER BY order_as_of_date"
    ).fetchall()
    print(f"distinct_dates({len(dates)}): {[d[0] for d in dates[:10]]}")
    if "fill_count" in cols:
        nulls = c.execute(
            "SELECT COUNT(*) FROM tca_route_summary WHERE fill_count IS NULL"
        ).fetchone()[0]
        non_null = count - nulls
        print(f"fill_count: non_null={non_null}, null={nulls}")
        sample = c.execute(
            "SELECT OrderId, RouteId, order_as_of_date, fill_count, fill "
            "FROM tca_route_summary LIMIT 3"
        ).fetchall()
        print(f"sample(oid,rid,date,fill_count,fill): {sample}")

conn.close()
