"""临时调试：route_registry 分区写入状态（execution_history.db）。"""
import sqlite3

DATA_DIR = r"c:\Users\hrchen\Documents\EMSXView\CostView\data"
eh = sqlite3.connect(DATA_DIR + r"\execution_history.db")

tables = [r[0] for r in eh.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print("execution_history.db 表:", tables)

if "route_registry" in tables:
    row = eh.execute("SELECT COUNT(*) FROM route_registry").fetchone()
    print(f"route_registry 行数: {row[0]}")
    row = eh.execute("SELECT COUNT(*) FROM route_registry WHERE ccy_ticker IS NOT NULL AND ccy_ticker != ''").fetchone()
    print(f"ccy_ticker 非空: {row[0]}")
    # 20260805 路由
    pf = sqlite3.connect(DATA_DIR + r"\processed_fills.db")
    oids = [str(r[0]) for r in pf.execute(
        "SELECT DISTINCT OrderId FROM processed_fills WHERE order_as_of_date='20260805' LIMIT 3"
    ).fetchall()]
    print("20260805 样例 OrderId:", oids)
    for oid in oids:
        n = eh.execute("SELECT COUNT(*) FROM route_registry WHERE OrderId = ?", (oid,)).fetchone()[0]
        print(f"  {oid}: registry rows = {n}")
    rows = eh.execute(
        "SELECT OrderId, RouteId, ccy_ticker, Exchange FROM route_registry LIMIT 5"
    ).fetchall()
    print("前 5 行:")
    for r in rows:
        print("  ", r)
    pf.close()
else:
    print("route_registry 表不存在于 execution_history.db！")
eh.close()
