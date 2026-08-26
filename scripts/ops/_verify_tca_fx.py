"""临时验证：tca_route_summary fx_rate 填充效果。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
fb = sqlite3.connect(DATA_DIR + r"\fill_bdib.db")

print("=== tca_route_summary fx_rate 分布（已重算日期 vs 未重算）===")
rows = fb.execute(
    """
    SELECT order_as_of_date, COUNT(*) AS total,
           SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END) AS null_cnt,
           SUM(CASE WHEN fx_rate = 1.0 THEN 1 ELSE 0 END) AS one_cnt,
           SUM(CASE WHEN fx_rate IS NOT NULL AND fx_rate != 1.0 THEN 1 ELSE 0 END) AS real_cnt
    FROM tca_route_summary
    GROUP BY order_as_of_date
    ORDER BY order_as_of_date DESC LIMIT 12
    """
).fetchall()
for r in rows:
    print(f"  {r[0]}: total={r[1]} fx_null={r[2]} fx_one={r[3]} fx_real={r[4]}")

print("\n=== 已重算日期的 fx_rate 样例 ===")
rows = fb.execute(
    """
    SELECT order_as_of_date, Exchange, Currency, fx_rate
    FROM tca_route_summary
    WHERE order_as_of_date = '20251003' AND fx_rate IS NOT NULL
    LIMIT 5
    """
).fetchall()
for r in rows:
    print("  ", r)
fb.close()
