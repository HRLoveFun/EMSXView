"""临时调试：route_registry 20260805 路由的 ccy_ticker 状态。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
pf = sqlite3.connect(DATA_DIR + r"\processed_fills.db")
fb = sqlite3.connect(DATA_DIR + r"\fill_bdib.db")

print("=== route_registry 中 20260805 路由样例 ===")
rows = pf.execute(
    """
    SELECT rr.OrderId, rr.RouteId, rr.ccy_ticker, rr.Exchange
    FROM route_registry rr
    JOIN (SELECT DISTINCT OrderId, RouteId FROM processed_fills WHERE order_as_of_date='20260805') k
      ON rr.OrderId = k.OrderId AND rr.RouteId = k.RouteId
    LIMIT 10
    """
).fetchall()
for r in rows:
    print("  ", r)
print(f"  匹配数: {len(rows)}")

print("\n=== route_registry 中 20260805 路由 ccy_ticker NULL 统计 ===")
row = pf.execute(
    """
    SELECT COUNT(*),
           SUM(CASE WHEN rr.ccy_ticker IS NULL OR TRIM(rr.ccy_ticker)='' THEN 1 ELSE 0 END)
    FROM route_registry rr
    JOIN (SELECT DISTINCT OrderId, RouteId FROM processed_fills WHERE order_as_of_date='20260805') k
      ON rr.OrderId = k.OrderId AND rr.RouteId = k.RouteId
    """
).fetchone()
print("  total/null =", row)

print("\n=== route_registry 中任意 20260805 路由是否存在 ===")
rows = pf.execute(
    "SELECT OrderId, RouteId, ccy_ticker FROM route_registry WHERE OrderId IN (SELECT DISTINCT OrderId FROM processed_fills WHERE order_as_of_date='20260805' LIMIT 5) LIMIT 10"
).fetchall()
for r in rows:
    print("  ", r)

print("\n=== fill_bdib 20260805 路由样例（当前状态）===")
rows = fb.execute(
    "SELECT OrderId, RouteId, ccy_ticker FROM fill_bdib WHERE order_as_of_date='20260805' LIMIT 5"
).fetchall()
for r in rows:
    print("  ", r)

pf.close()
fb.close()
