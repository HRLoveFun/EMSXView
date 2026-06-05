"""生成边界测试 baseline 报告。

执行: python backend/api/tests/boundaries/scripts/generate_baseline.py
"""
import json
import re
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
REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "roadmap"
    / "boundary-baseline.md"
)

# 严重度映射
SEVERITY = {
    "AP-01": "critical",
    "AP-02": "critical",
    "AP-04": "critical",
    "AP-07": "critical",
    "AP-08": "critical",
    "AP-05": "high",
    "AP-09": "high",
    "AP-12": "high",
    "AP-13": "high",
    "AP-03": "high",
    "AP-06": "low",
    "AP-10": "medium",
    "AP-11": "medium",
    "AP-14": "medium",
    "AP-15": "medium",
    "DOC-DRIFT": "medium",
}

SLA = {
    "critical": "1 周内",
    "high": "2 周内",
    "medium": "1 月内",
    "low": "2 月内",
}


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

    # 写 markdown 报告
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Boundary Violations Baseline",
        "",
        f"Generated: {baseline['generated_at']} | Total: **{baseline['total']}**",
        "",
        "> AI agent 与开发者按严重度分批修复。",
        "> 修复后本文件需重新生成。",
        "",
    ]

    # 按严重度分组
    by_severity: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for rule_id, items in by_rule.items():
        sev = SEVERITY.get(rule_id, "medium")
        by_severity[sev].append((rule_id, items))

    for sev in ("critical", "high", "medium", "low"):
        if sev not in by_severity:
            continue
        rules = by_severity[sev]
        total = sum(len(items) for _, items in rules)
        lines.append(f"## {sev.upper()} ({total}) - Fix within {SLA[sev]}")
        lines.append("")
        for rule_id, items in sorted(rules, key=lambda x: -len(x[1])):
            lines.append(f"### {rule_id} ({len(items)})")
            for v in items[:20]:  # 每条最多显示 20
                lines.append(
                    f"- `{v['file']}`:{v.get('line', 0)}  {v['message']}"
                )
                if v.get("fix_hint"):
                    lines.append(f"  - Fix: {v['fix_hint']}")
            if len(items) > 20:
                lines.append(f"- ... and {len(items) - 20} more")
        lines.append("")

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] report written: {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
