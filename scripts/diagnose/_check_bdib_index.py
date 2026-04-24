import sqlite3, time
conn = sqlite3.connect('file:CostView/data/raw_fills.db?mode=ro', uri=True)
t = time.time()
print('min_no_where:', conn.execute('SELECT MIN(order_as_of_date) FROM raw_fills').fetchone(), round(time.time()-t, 2), 's')
t = time.time()
print('min_with_where:', conn.execute("SELECT MIN(order_as_of_date) FROM raw_fills WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''").fetchone(), round(time.time()-t, 2), 's')
t = time.time()
print('eqp:', conn.execute("EXPLAIN QUERY PLAN SELECT MIN(order_as_of_date) FROM raw_fills WHERE order_as_of_date IS NOT NULL AND order_as_of_date != ''").fetchall(), round(time.time()-t, 2), 's')
