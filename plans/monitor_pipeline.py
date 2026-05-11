"""Monitor pipeline progress — polls every 30s for up to 15 minutes."""
import json
import time
import urllib.request

JOB_ID = "2c36c9eb-4091-4904-af4a-c174f6a2538a"
URL = "http://127.0.0.1:3000/api/db/update-status/" + JOB_ID
MAX_POLLS = 60  # 30 min at 30s intervals

for i in range(1, MAX_POLLS + 1):
    try:
        resp = urllib.request.urlopen(URL, timeout=10)
        data = json.loads(resp.read().decode())
        s = data.get("stage") or {}
        detail = (s.get("detail") or "")[:70]
        last_act = (data.get("last_activity_at") or "")[-19:-7]
        print(
            f"[{i:2d}/{MAX_POLLS}] {data['status']:10s} | "
            f"overall={data['overall_progress']:3d}% | "
            f"{s.get('name','?'):15s} {s.get('progress',0):3d}% | "
            f"detail={detail} | "
            f"last_act={last_act}"
        )
        if data["status"] in ("completed", "failed"):
            print(f"=== Pipeline {data['status'].upper()} ===")
            if data.get("error"):
                print(f"Error: {data['error'][:200]}")
            break
    except Exception as e:
        print(f"[{i:2d}] ERROR: {e}")
    time.sleep(30)
