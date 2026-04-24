"""Reproduce the backend's pipeline subprocess flow to see why it fails instantly."""
import subprocess
import sys
import time
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "CostView" / "scripts" / "daily_update.py"
print(f"Running: {sys.executable} -u {script} --once")
t0 = time.time()

proc = subprocess.Popen(
    [sys.executable, "-u", str(script), "--once"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

lines = []
while True:
    line = proc.stdout.readline() if proc.stdout else ""
    if not line and proc.poll() is not None:
        break
    if line:
        lines.append(line.rstrip())
        print(f"  {line.rstrip()}")
    if time.time() - t0 > 5:
        print(f"\n>>> 5s elapsed, killing (normal flow, just to show output so far)")
        proc.kill()
        break

output, _ = proc.communicate()
print(f"\nRC: {proc.returncode}")
print(f"Post-communicate output ({len(output)} chars): {output[:500]!r}")
print(f"Total lines captured in loop: {len(lines)}")
print(f"Elapsed: {time.time() - t0:.2f}s")
