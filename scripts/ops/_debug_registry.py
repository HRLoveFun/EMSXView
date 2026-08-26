"""临时调试：route_registry 当前状态。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
pf = sqlite3.connect(DATA_DIR + r"\processed_fills.db")

print("=== route_registry 总行数 ===")
print(" ", pf.execute("SELECT COUNT(*) FROM route_registry").fetchone()[0])

print("\n=== route_registry 日期分布（通过 join processed_fills 推断）===")
rows = pf.execute(
    """
    SELECT p.order_as_of_date, COUNT(DISTINCT rr.OrderId || '|' || rr.RouteId)
    FROM route_registry rr
    JOIN processed_fills p ON rr.OrderId = p.OrderId AND rr.RouteId = p.RouteId
    GROUP BY p.order_as_of_date ORDER BY p.order_as_of_date DESC LIMIT 15
    """
).fetchall()
for r in rows:
    print("  ", r)

print("\n=== processed_fills 20260805 路由样例（OrderId）===")
rows = pf.execute(
    "SELECT DISTINCT OrderId FROM processed_fills WHERE order_as_of_date='20260805' LIMIT 5"
).fetchall()
print("  ", [r[0] for r in rows])

print("\n=== route_registry 中这些 OrderId 是否存在 ===")
oids = [r[0] for r in rows]
for oid in oids:
    n = pf.execute("SELECT COUNT(*) FROM route_registry WHERE OrderId = ?", (str(oid),)).fetchone()[0]
    print(f"  {oid}: registry rows = {n}")

print("\n=== route_registry 前 3 行样例 ===")
for r in pf.execute("SELECT * FROM route_registry LIMIT 3").fetchall():
    print("  ", r)

print("\n=== route_registry OrderId 类型样例（text vs int）===")
rows = pf.execute("SELECT OrderId, RouteId, typeof(OrderId), typeof(RouteId) FROM route_registry LIMIT 5").fetchall()
for r in rows:
    print("  ", r)
rows = pf.execute("SELECT OrderId, RouteId, typeof(OrderId), typeof(RouteId) FROM processed_fills WHERE order_as_of_date='20260805' LIMIT 5").fetchall()
for r in rows:
    print("  pf:", r)

pf.close()
