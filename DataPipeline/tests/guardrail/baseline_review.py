"""基线快照更新审批工具。

提供 CLI 命令用于基线更新审批流程：
  python -m DataPipeline.tests.guardrail.baseline_review --stage S2 --new-baseline <path>
  生成新旧基线差异报告（JSON diff 格式），经 Reviewer 确认后执行 --approve 归档。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASELINE_DIR = Path(__file__).resolve().parent.parent / "baselines"


def load_baseline(stage: str) -> dict[str, Any] | list[Any]:
    """加载现有基线快照"""
    baseline_path = BASELINE_DIR / f"{stage}_output.json"
    if not baseline_path.exists():
        print(f"[WARNING] 基线文件不存在: {baseline_path}")
        return {}
    return json.loads(baseline_path.read_text(encoding="utf-8"))


def load_new_baseline(path: str) -> dict[str, Any] | list[Any]:
    """加载新基线候选文件"""
    new_path = Path(path)
    if not new_path.exists():
        print(f"[ERROR] 新基线文件不存在: {new_path}")
        sys.exit(1)
    return json.loads(new_path.read_text(encoding="utf-8"))


def generate_diff(old: Any, new: Any, path: str = "") -> list[str]:
    """生成新旧基线的 JSON diff 报告"""
    diffs: list[str] = []

    if type(old) != type(new):
        diffs.append(f"{path}: 类型变更 {type(old).__name__} → {type(new).__name__}")
        return diffs

    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            key_path = f"{path}.{key}" if path else key
            if key not in old:
                diffs.append(f"+ {key_path}: 新增字段")
            elif key not in new:
                diffs.append(f"- {key_path}: 删除字段")
            elif old[key] != new[key]:
                diffs.append(f"~ {key_path}: {old[key]} → {new[key]}")

    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            diffs.append(f"{path}: 记录数变更 {len(old)} → {len(new)}")

    elif old != new:
        diffs.append(f"{path}: {old} → {new}")

    return diffs


def approve_baseline(stage: str, new_data: Any) -> None:
    """审批并归档新基线"""
    backup_path = BASELINE_DIR / f"{stage}_output_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

    # 备份旧基线
    old_path = BASELINE_DIR / f"{stage}_output.json"
    if old_path.exists():
        old_path.rename(backup_path)
        print(f"[INFO] 旧基线已备份: {backup_path}")

    # 写入新基线
    old_path.write_text(
        json.dumps(new_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[SUCCESS] 阶段 {stage} 基线已更新")


def main() -> None:
    parser = argparse.ArgumentParser(description="基线快照更新审批工具")
    parser.add_argument("--stage", required=True, help="阶段名称（如 S2）")
    parser.add_argument("--new-baseline", dest="new_baseline", help="新基线候选文件路径")
    parser.add_argument("--approve", action="store_true", help="审批并归档新基线")
    args = parser.parse_args()

    if args.new_baseline:
        old = load_baseline(args.stage)
        new = load_new_baseline(args.new_baseline)
        diffs = generate_diff(old, new)

        print(f"\n{'='*60}")
        print(f"基线差异报告: 阶段 {args.stage}")
        print(f"{'='*60}")

        if not diffs:
            print("无差异 — 新旧基线完全一致")
        else:
            for diff in diffs:
                print(f"  {diff}")

        print(f"\n如需审批，请运行:")
        print(f"  python -m DataPipeline.tests.guardrail.baseline_review --stage {args.stage} --approve")
        print()

    elif args.approve:
        if not args.new_baseline:
            print("[ERROR] --approve 需要配合 --new-baseline 使用")
            sys.exit(1)
        new = load_new_baseline(args.new_baseline)
        approve_baseline(args.stage, new)


if __name__ == "__main__":
    main()
