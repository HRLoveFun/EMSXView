"""临时检查：0 匹配日期的 fill_bdib 存在性 + fill_bdib 全部日期清单。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
fb = sqlite3.connect(DATA_DIR + r"\fill_bdib.db")
pf = sqlite3.connect(DATA_DIR + r"\processed_fills.db")

zero_dates = ["20260414", "20260415", "20260511", "20260512", "20260527",
              "20260602", "20260603", "20260604", "20260706", "20260707", "20260824"]
print("=== 0 匹配日期在 fill_bdib 中的存在性 ===")
for d in zero_dates:
    n = fb.execute("SELECT COUNT(*) FROM fill_bdib WHERE order_as_of_date=?", (d,)).fetchone()[0]
    print(f"  {d}: fill_bdib rows = {n}")

print("\n=== fill_bdib 全部日期（按顺序）===")
rows = fb.execute("SELECT DISTINCT order_as_of_date FROM fill_bdib ORDER BY order_as_of_date").fetchall()
dates = [str(r[0]) for r in rows]
print(f"  共 {len(dates)} 个日期")
print("  前 10:", dates[:10])
print("  后 10:", dates[-10:])

fb.close()
pf.close()
