"""监控 tca_route_summary 表的更新与管线日志。

用法:
    python scripts/monitor_trs.py [duration_seconds] [poll_interval_seconds]

默认 duration=120s, interval=10s
"""
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# PowerShell cp1252 兼容：重定向 stdout 到 utf-8（避免中文崩溃）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB_PATH = Path(r"C:\Users\hrchen\Documents\EMSXView\CostView\data\fill_bdib.db")
LOG_PATH = Path(r"C:\Users\hrchen\Documents\EMSXView\logs\pipeline\fillfetch.log")
LOG_OFFSET = Path(r"C:\Users\hrchen\Documents\EMSXView\logs\monitor_trs.offset")

duration = int(sys.argv[1]) if len(sys.argv) > 1 else 120
interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
end_time = time.time() + duration

# 记录上次读取日志的字节偏移
start_offset = 0
if LOG_OFFSET.exists():
    try:
        start_offset = int(LOG_OFFSET.read_text().strip())
    except Exception:
        start_offset = 0

print(f"=== tca_route_summary Monitor ===")
print(f"DB: {DB_PATH}")
print(f"Log: {LOG_PATH}")
print(f"Start time: {datetime.now().isoformat()}")
print(f"Duration: {duration}s, Poll interval: {interval}s")
print(f"Log start offset: {start_offset}")
print("=" * 60)

prev_count = -1
prev_dates = set()
prev_sample = None
tick = 0

try:
    while time.time() < end_time:
        tick += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[Tick {tick} @ {ts}]")

        # 1. 检查 tca_route_summary 状态
        if not DB_PATH.exists():
            print(f"  DB not found: {DB_PATH}")
        else:
            conn = sqlite3.connect(str(DB_PATH))
            c = conn.cursor()
            t = c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tca_route_summary'"
            ).fetchone()
            if not t:
                print("  tca_route_summary: table NOT CREATED yet")
            else:
                count = c.execute("SELECT COUNT(*) FROM tca_route_summary").fetchone()[0]
                cols = [d[0] for d in c.execute("SELECT * FROM tca_route_summary LIMIT 1").description]
                has_fc = "fill_count" in cols
                dates = [d[0] for d in c.execute(
                    "SELECT DISTINCT order_as_of_date FROM tca_route_summary "
                    "ORDER BY order_as_of_date"
                ).fetchall()]
                date_set = set(dates)

                delta = count - prev_count if prev_count >= 0 else 0
                new_dates = sorted(date_set - prev_dates)
                print(f"  rows: {count} ({'+' + str(delta) if delta > 0 else str(delta) if delta else '='})")
                print(f"  fill_count column: {has_fc}")
                print(f"  dates ({len(dates)}): {dates[:8]}{' ...' if len(dates) > 8 else ''}")
                if new_dates:
                    print(f"  NEW dates: {new_dates}")

                if count > 0:
                    sample = c.execute(
                        "SELECT OrderId, RouteId, order_as_of_date, fill_count, fill, pnl_vwap "
                        "FROM tca_route_summary ORDER BY rowid DESC LIMIT 3"
                    ).fetchall()
                    print(f"  recent sample (oid,rid,date,fill_count,fill,pnl_vwap):")
                    for row in sample:
                        print(f"    {row}")
                    null_fc = c.execute(
                        "SELECT COUNT(*) FROM tca_route_summary WHERE fill_count IS NULL"
                    ).fetchone()[0]
                    if has_fc and null_fc:
                        print(f"  ⚠ fill_count IS NULL: {null_fc} rows")

                prev_count = count
                prev_dates = date_set
            conn.close()

        # 2. 检查管线进程
        # 3. 读取新增日志
        if LOG_PATH.exists():
            sz = LOG_PATH.stat().st_size
            if sz > start_offset:
                with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(start_offset)
                    new_text = f.read()
                start_offset = sz
                LOG_OFFSET.write_text(str(start_offset))
                if new_text.strip():
                    lines = new_text.strip().splitlines()
                    # 只显示最后 15 行 + STAGE 行
                    stage_lines = [l for l in lines if "[STAGE]" in l]
                    tail_lines = lines[-15:] if len(lines) > 15 else lines
                    print(f"  --- log delta: {len(lines)} lines ---")
                    for ln in stage_lines[-5:]:
                        print(f"    {ln}")
                    if len(lines) > 0:
                        last = lines[-1] if lines else ""
                        if "[STAGE]" not in last:
                            print(f"    LAST: {last[:200]}")

        # 4. 等待
        if time.time() < end_time:
            time.sleep(interval)
except KeyboardInterrupt:
    pass
finally:
    LOG_OFFSET.write_text(str(start_offset))

print("\n" + "=" * 60)
print(f"Monitor ended at {datetime.now().isoformat()}")
print(f"Final log offset: {start_offset}")
