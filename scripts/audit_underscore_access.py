"""适配器下划线访问审计 (AP-08)。

检测跨域代码调用 ``platform_data`` 适配器的 ``_`` 前缀私有方法 —
公开/私有分界防止内部实现细节泄漏到跨域调用方。

用法::

    python scripts/audit_underscore_access.py
    python scripts/audit_underscore_access.py --json

退出码: 0=无违规, 1=存在违规
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Windows 控制台 (cp1252) 下强制 UTF-8 stdout, 避免中文审计输出抛 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]

# 跨域调用方扫描根 (platform_data 自身内部访问 _ 前缀不视为越界)
SCAN_ROOTS: list[tuple[Path, str]] = [
    (REPO_ROOT / "backend", "*.py"),
    (REPO_ROOT / "frontend" / "src", "*.ts"),
    (REPO_ROOT / "CostView" / "src", "*.py"),
    (REPO_ROOT / "DataPipeline", "*.py"),
]

# 下划线私有成员访问模式: platform_data.<module>._private (点后紧跟下划线)
_UNDERSCORE_ACCESS = re.compile(r"platform_data\.\w+\._\w+")

# 豁免: 测试/审计代码有意探测私有方法 (仅内部使用)
EXEMPT_FILES = {
    "backend/api/tests/test_handoff_capacity.py",  # H4 回归测试需构造过期条目
}


def run_audit() -> list[dict]:
    """返回违规列表 [{path, line, snippet}]。"""
    violations: list[dict] = []
    for base_dir, suffix in SCAN_ROOTS:
        if not base_dir.exists():
            continue
        for file_path in base_dir.rglob(suffix):
            rel = file_path.relative_to(REPO_ROOT).as_posix()
            if rel in EXEMPT_FILES:
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, start=1):
                for m in _UNDERSCORE_ACCESS.finditer(line):
                    violations.append({
                        "path": rel,
                        "line": lineno,
                        "snippet": m.group(0),
                    })
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="适配器下划线访问审计 (AP-08)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    violations = run_audit()

    if args.json:
        print(json.dumps({"violations": violations}, ensure_ascii=False, indent=2))
    elif violations:
        print(f"[AP-08] 发现 {len(violations)} 处适配器私有方法访问:")
        for v in violations:
            print(f"  {v['path']}:{v['line']} -> {v['snippet']}")
        print("修复: 改用适配器公开 API (无下划线前缀)")
    else:
        print("[AP-08] 下划线访问审计通过, 无违规")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
