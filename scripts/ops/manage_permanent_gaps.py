"""管理永久空缺交易日 tombstone（`Config.PERMANENT_GAP_DATES_FILE`）。

用法：
    # 列出全部永久空缺日期
    python scripts/ops/manage_permanent_gaps.py

    # 标记某日期为永久空缺（幂等）
    python scripts/ops/manage_permanent_gaps.py --mark 20260708 --reason retention_window_expired

    # 取消标记（数据恢复后）
    python scripts/ops/manage_permanent_gaps.py --unmark 20260708
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from DataPipeline.common.permanent_gap_dates import (
    load_permanent_gap_records,
    record_permanent_gap,
    remove_permanent_gap,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="管理永久空缺交易日 tombstone")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mark", metavar="YYYYMMDD", help="标记为永久空缺")
    group.add_argument("--unmark", metavar="YYYYMMDD", help="取消永久空缺标记")
    parser.add_argument("--reason", default="retention_window_expired",
                        help="标记原因（默认 retention_window_expired）")
    parser.add_argument("--detail", help="补充说明")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)

    if args.mark:
        rec = record_permanent_gap(args.mark, reason=args.reason, detail=args.detail)
        print(f"已标记永久空缺: {rec['date']} ({rec['reason']})")
        return 0
    if args.unmark:
        ok = remove_permanent_gap(args.unmark)
        print(f"已取消标记: {args.unmark}" if ok else f"未找到标记: {args.unmark}")
        return 0 if ok else 1

    records = load_permanent_gap_records()
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    elif records:
        print(f"永久空缺交易日（{len(records)} 个）：")
        for d, rec in records.items():
            print(f"  {d}: {rec['reason']} (记录于 {rec['last_seen_at']})")
    else:
        print("无永久空缺交易日记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
