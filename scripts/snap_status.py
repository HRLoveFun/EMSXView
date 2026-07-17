"""一次性状态汇总：日志尾部 + fill_bdib + tca_route_summary + 进程。"""
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

# PowerShell cp1252 兼容：重定向 stdout 到 utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOG = Path(r"C:\Users\hrchen\Documents\EMSXView\logs\pipeline\fillfetch.log")
DB = Path(r"C:\Users\hrchen\Documents\EMSXView\CostView\data\fill_bdib.db")

def file_mtime(p: Path):
    if not p.exists():
        return None
    return datetime.fromtimestamp(p.stat().st_mtime).isoformat(sep=" ", timespec="seconds")

# 1. 日志尾部
print("=" * 60)
print(f"LOG: {LOG}  size={LOG.stat().st_size if LOG.exists()  else 'N/A'}  mtime={file_mtime(LOG)}")
print("=" * 60)
if LOG.exists():
    with open(LOG, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        back = min(size, 5000)
        f.seek(size - back)
        data = f.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    print(f"--- last {min(40, len(lines))} lines (of {len(lines)} shown) ---")
    for ln in lines[-40:]:
        print(ln)
    stages = [l for l in lines if "==> Starting Stage" in l or "GuardPipeline" in l or "ComputeRoute" in l or "tca_route" in l]
    print(f"\n--- {len(stages)} STAGE / pipeline markers ---")
    for s in stages[-15:]:
        print(s)

# 2. fill_bdib.db
print("\n" + "=" * 60)
print(f"DB: {DB}  exists={DB.exists()}  mtime={file_mtime(DB)}  size={DB.stat().st_size if DB.exists() else 'N/A'}")
print("=" * 60)
if DB.exists():
    conn = sqlite3.connect(str(DB))
    c = conn.cursor()
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    print(f"tables({len(tables)}): {tables}")
    for t in tables:
        try:
            cnt = c.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            print(f"  {t}: {cnt} rows")
        except Exception as e:
            print(f"  {t}: error {e}")
    conn.close()

# 3. 进程
print("\n" + "=" * 60)
print("Python processes (live):")
print("=" * 60)
try:
    import psutil
    for p in psutil.process_iter(["pid", "name", "create_time", "cpu_times", "memory_info"]):
        try:
            if "python" in (p.info["name"] or "").lower():
                cpu = p.info["cpu_times"]
                runtime = (cpu.user + cpu.system) if cpu else 0
                mem_mb = p.info["memory_info"].rss / (1024 * 1024) if p.info["memory_info"] else 0
                print(f"  pid={p.info['pid']} name={p.info['name']} "
                      f"started={datetime.fromtimestamp(p.info['create_time']).isoformat(sep=' ', timespec='seconds')} "
                      f"cpu_total_s={runtime:.1f} rss_mb={mem_mb:.0f}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
except ImportError:
    print("  psutil not available")
