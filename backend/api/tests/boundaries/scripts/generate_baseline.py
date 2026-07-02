"""生成边界测试 baseline 报告。

执行: python backend/api/tests/boundaries/scripts/generate_baseline.py
"""
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
VIOLATIONS_LOG = (
    REPO_ROOT
    / "backend"
    / "api"
    / "tests"
    / "boundaries"
    / ".scan_log.jsonl"
)
BASELINE_JSON = (
    REPO_ROOT
    / "backend"
    / "api"
    / "tests"
    / "boundaries"
    / "baseline_violations.json"
)


def main() -> int:
    if not VIOLATIONS_LOG.exists():
        print(f"[ERR] violations log not found: {VIOLATIONS_LOG}")
        print("Please run boundary tests first: pytest backend/api/tests/boundaries/ -v")
        return 1

    # 读取 .scan_log.jsonl 并按 (file, rule_id) 去重
    violations_by_key: dict[tuple[str, str], dict] = {}
    with VIOLATIONS_LOG.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                v = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (v["file"], v["rule_id"])
            # 保留首次出现
            if key not in violations_by_key:
                violations_by_key[key] = v

    # 按 rule_id 分组
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for v in violations_by_key.values():
        by_rule[v["rule_id"]].append(v)

    # 写 baseline JSON（用于测试套件去重）
    baseline = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(violations_by_key),
        "by_rule": {r: len(items) for r, items in by_rule.items()},
        "violations": [
            {
                "key": f"{v['file']}::{v['rule_id']}",
                "rule_id": v["rule_id"],
                "file": v["file"],
                "line": v.get("line", 0),
                "message": v["message"],
                "fix_hint": v.get("fix_hint", ""),
            }
            for v in violations_by_key.values()
        ],
    }
    BASELINE_JSON.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_JSON.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] baseline written: {BASELINE_JSON} ({baseline['total']} violations)")
    print("[INFO] markdown 报告已废弃，baseline_violations.json 为唯一真理源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
