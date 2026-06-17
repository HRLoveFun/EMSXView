"""Quick production-validation report for regime.db."""
import os
import sqlite3
from pathlib import Path

# 数据库路径由 EMSXVIEW_DATA_DIR 环境变量控制，未设置时回退到项目内默认路径
_data_dir = Path(os.getenv("EMSXVIEW_DATA_DIR", str(
    Path(__file__).resolve().parents[2] / "CostView" / "data"
)))
conn = sqlite3.connect(str(_data_dir / "regime.db"))

print('=== daily_market_index 行数/市场覆盖 ===')
sql = """
SELECT market_code, COUNT(*) n,
       SUM(CASE WHEN px_last IS NOT NULL THEN 1 ELSE 0 END) px_ok,
       SUM(CASE WHEN vol_index_value IS NOT NULL THEN 1 ELSE 0 END) vix_ok,
       SUM(CASE WHEN turnover IS NOT NULL THEN 1 ELSE 0 END) turn_ok,
       SUM(CASE WHEN rsi_30d IS NOT NULL THEN 1 ELSE 0 END) rsi_ok
FROM daily_market_index GROUP BY market_code ORDER BY market_code
"""
print(f"  {'mkt':4s}  rows  px  vix  turn  rsi")
for r in conn.execute(sql).fetchall():
    print(f"  {r[0]:4s}  {r[1]:3d}  {r[2]:3d}  {r[3]:3d}  {r[4]:3d}  {r[5]:3d}")

print('\n=== 标签分布（按 regime）===')
for col in ('vol_regime', 'liq_regime', 'trend_regime'):
    print(f'-- {col}')
    for r in conn.execute(f'SELECT {col}, COUNT(*) FROM fill_regime_labels GROUP BY {col}').fetchall():
        print(f'    {r[0]}: {r[1]:,}')

print('\n=== macro_event_window 标记 ===')
for r in conn.execute('SELECT macro_event_window, COUNT(*) FROM fill_regime_labels GROUP BY macro_event_window').fetchall():
    print(f'  flag={r[0]}: {r[1]:,}')

print('\n=== fill_regime_labels by market (top 10) ===')
for r in conn.execute('SELECT market_code, COUNT(*) FROM fill_regime_labels GROUP BY market_code ORDER BY 2 DESC LIMIT 10').fetchall():
    print(f'  {r[0]:4s}: {r[1]:,}')

print('\n=== audit_pipeline_runs ===')
for r in conn.execute('SELECT stage_name, status, rows_written, duration_sec FROM audit_pipeline_runs ORDER BY run_id').fetchall():
    dur = f"{r[3]:.2f}s" if r[3] else 'n/a'
    print(f'  {r[0]:25s}  {r[1]:8s}  rows={r[2]:>7}  {dur}')

print('\n=== regime_status view ===')
for r in conn.execute('SELECT * FROM regime_status').fetchall():
    print(f'  {r}')
