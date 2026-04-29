import time, sqlite3
time.sleep(1500)
c = sqlite3.connect('CostView/data/regime.db')
n = c.execute('SELECT COUNT(DISTINCT order_as_of_date_iso) FROM fill_attribution_metrics').fetchone()[0]
mx = c.execute('SELECT MAX(order_as_of_date_iso) FROM fill_attribution_metrics').fetchone()[0]
print(f'dates={n}/149 max={mx}')
