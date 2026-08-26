"""临时验证：20260805 专项 + fill_bdib 整体状态。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
fb = sqlite3.connect(DATA_DIR + r"\fill_bdib.db")

print("=== fill_bdib 20260805 现状 ===")
rows = fb.execute(
    """
    SELECT ccy_ticker, COUNT(*) AS n,
           SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END) AS null_cnt,
           SUM(CASE WHEN fx_rate = 1.0 THEN 1 ELSE 0 END) AS one_cnt
    FROM fill_bdib WHERE order_as_of_date = '20260805'
    GROUP BY ccy_ticker ORDER BY n DESC LIMIT 10
    """
).fetchall()
for r in rows:
    print("  ", r)
row = fb.execute(
    "SELECT COUNT(*), SUM(CASE WHEN ccy_ticker IS NULL THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END) "
    "FROM fill_bdib WHERE order_as_of_date='20260805'"
).fetchone()
print(f"  合计: total={row[0]} ccy_null={row[1]} fx_null={row[2]}")

print("\n=== fill_bdib 整体状态（全部日期汇总）===")
row = fb.execute(
    "SELECT COUNT(*), "
    "SUM(CASE WHEN ccy_ticker IS NULL OR TRIM(ccy_ticker)='' THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN fx_rate = 1.0 THEN 1 ELSE 0 END), "
    "SUM(CASE WHEN fx_rate IS NOT NULL AND fx_rate != 1.0 THEN 1 ELSE 0 END) "
    "FROM fill_bdib"
).fetchone()
print(f"  total={row[0]} ccy_null={row[1]} fx_null={row[2]} fx_one={row[3]} fx_real={row[4]}")

print("\n=== fill_bdib 仍缺失 ccy_ticker 的日期 ===")
rows = fb.execute(
    "SELECT DISTINCT order_as_of_date FROM fill_bdib "
    "WHERE ccy_ticker IS NULL OR TRIM(ccy_ticker)=''"
).fetchall()
print("  ", [r[0] for r in rows] if rows else "  无（全部已修复）")

print("\n=== fill_bdib fx_rate 缺失的日期（近 15）===")
rows = fb.execute(
    """
    SELECT order_as_of_date, COUNT(*) AS total,
           SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END) AS null_cnt
    FROM fill_bdib GROUP BY order_as_of_date
    HAVING null_cnt > 0 ORDER BY order_as_of_date DESC LIMIT 15
    """
).fetchall()
for r in rows:
    print(f"  {r[0]}: fx_null={r[2]}/{r[1]}")
fb.close()
