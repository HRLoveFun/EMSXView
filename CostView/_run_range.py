"""Run full pipeline for date range 20260101-20260414."""
import sys
import logging
import json
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

sys.path.insert(0, r"c:\Users\hrchen\Documents\EMSX\CostView")

from src.pipeline import run_full_pipeline

# Build date range 2026-01-01 to 2026-04-14 using proper YYYYMMDD format
start = datetime(2026, 1, 1)
end = datetime(2026, 4, 14)
dates = []
current = start
while current <= end:
    if current.weekday() < 5:  # Only weekdays
        dates.append(current.strftime("%Y%m%d"))
    current += __import__('datetime').timedelta(days=1)

print(f"Total dates: {len(dates)}, from {dates[0] if dates else 'NONE'} to {dates[-1] if dates else 'NONE'}", flush=True)
print("=" * 60, flush=True)

summary = run_full_pipeline(
    skip_bdib=False,
    skip_ingest=True,
    dates=dates,
)

print("=" * 60, flush=True)
print("Pipeline Summary:", flush=True)
print(json.dumps(summary, indent=2, default=str), flush=True)
