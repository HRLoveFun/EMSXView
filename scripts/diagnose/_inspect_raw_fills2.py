import sqlite3
c = sqlite3.connect('file:CostView/data/raw_fills.db?mode=ro', uri=True)
print("Top 10 distinct substr(order_as_of_date,1,10):")
for r in c.execute("SELECT substr(order_as_of_date,1,10) AS d, COUNT(*) FROM raw_fills WHERE order_as_of_date > '' GROUP BY d ORDER BY d DESC LIMIT 10"):
    print(" ", r)
print()
print("source_date max/min:")
print(" MIN:", c.execute("SELECT MIN(source_date) FROM raw_fills WHERE source_date > ''").fetchone())
print(" MAX:", c.execute("SELECT MAX(source_date) FROM raw_fills WHERE source_date > ''").fetchone())
print()
print("Top 10 distinct source_date:")
for r in c.execute("SELECT source_date, COUNT(*) FROM raw_fills GROUP BY source_date ORDER BY source_date DESC LIMIT 10"):
    print(" ", r)
