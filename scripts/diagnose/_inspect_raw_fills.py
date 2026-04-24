import sqlite3
conn = sqlite3.connect('file:CostView/data/raw_fills.db?mode=ro', uri=True)
print('Columns:')
for r in conn.execute('PRAGMA table_info(raw_fills)'):
    print(' ', r)
print()
print('Sample rows (last 3 by rowid):')
for r in conn.execute('SELECT rowid, order_as_of_date FROM raw_fills ORDER BY rowid DESC LIMIT 3'):
    print(' ', r)
print()
print('MIN/MAX order_as_of_date (no filter):')
print(' MIN:', conn.execute('SELECT MIN(order_as_of_date) FROM raw_fills').fetchone())
print(' MAX:', conn.execute('SELECT MAX(order_as_of_date) FROM raw_fills').fetchone())
print()
print('typeof sample:')
for r in conn.execute("SELECT typeof(order_as_of_date), order_as_of_date FROM raw_fills LIMIT 5"):
    print(' ', r)
print()
print("Max with > '' filter:")
print(' MAX:', conn.execute("SELECT MAX(order_as_of_date) FROM raw_fills WHERE order_as_of_date > ''").fetchone())
print()
print('Distinct length distribution:')
for r in conn.execute("SELECT LENGTH(order_as_of_date) AS L, COUNT(*) FROM raw_fills GROUP BY L ORDER BY L"):
    print(' ', r)
print()
print('Top 5 MAX distinct:')
for r in conn.execute("SELECT DISTINCT order_as_of_date FROM raw_fills ORDER BY order_as_of_date DESC LIMIT 5"):
    print(' ', r)
