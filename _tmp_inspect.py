import sqlite3
for db in ['raw_bdib.db','processed_fills.db','raw_fills.db','fill_bdib.db']:
    p = rf'CostView\data\{db}'
    c = sqlite3.connect(p); cur = c.cursor()
    print(f'=== {db} ===')
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    print(' tables:', tables)
    for t in tables:
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            n = cur.fetchone()[0]
            print(f'  {t}: rows={n:,}')
        except Exception as e:
            print(f'  {t}: ERR {e}')
    c.close()
