"""Monitor pipeline progress — polls every 30s for up to 15 minutes."""
import json
import time
import urllib.request

JOB_ID = "719eee85-38e1-46b3-9563-ca2ddee7b7e0"
URL = "http://127.0.0.1:3000/api/db/update-status/" + JOB_ID
MAX_POLLS = 30

for i in range(1, MAX_POLLS + 1):
    try:
        resp = urllib.request.urlopen(URL, timeout=10)
        data = json.loads(resp.read().decode())
        s = data.get("stage") or {}
        detail = (s.get("detail") or "")[:70]
        la = (data.get("last_activity_at") or "")[-8:]
        print(
            f"[{i:2d}/{MAX_POLLS}] {data['status']:10s} "
            f"overall={data['overall_progress']:3d}% | "
            f"{s.get('name','?'):15s} {s.get('progress',0):3d}% | "
            f"{detail} | act={la}"
        )
        if data["status"] in ("completed", "failed"):
            err = data.get("error") or ""
            print(f"=== DONE: {data['status'].upper()} ===")
            if err:
                print(f"Error: {err[:300]}")
            break
    except Exception as e:
        print(f"[{i:2d}] ERROR: {e}")
    time.sleep(30)
