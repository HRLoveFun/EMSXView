"""影子周报 CLI（057 DL-22/215）。

只读聚合运营库的 `routing_decisions`，按 ISO 周输出：
覆盖率、一致率、改写率与原因分布、硬违例、预期成本（缺估计时显式不可得）。

用法：
    python scripts/qa/shadow_weekly_report.py
    python scripts/qa/shadow_weekly_report.py --start 20261117 --end 20261123

输出：`logs/qa/shadow/shadow_weekly_<start>_<end>.json`，并打印 totals 摘要。

环境：与 backend 使用同一 `DATABASE_URL` / `EMSXVIEW_OPS_DB_DIR`；全新库先 `--init`。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_API_ROOT = _REPO_ROOT / "backend" / "api"
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

# config 在 import 时校验 JWT_SECRET（部署闸门）；只读 CLI 给一个占位值
os.environ.setdefault("JWT_SECRET", "shadow-weekly-readonly-cli-0123456789abcdef0123456789abcdef")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shadow weekly report (057 DL-22/215)")
    parser.add_argument("--start", default="", help="YYYYMMDD (default: 7 days ago)")
    parser.add_argument("--end", default="", help="YYYYMMDD (default: today)")
    parser.add_argument("--out-dir", default=str(_REPO_ROOT / "logs" / "qa" / "shadow"))
    parser.add_argument(
        "--init", action="store_true",
        help="create the ops schema first (needed on a fresh DB before the backend has run)",
    )
    args = parser.parse_args(argv)

    end = args.end or datetime.now().strftime("%Y%m%d")
    start = args.start or (
        datetime.strptime(end, "%Y%m%d") - timedelta(days=6)
    ).strftime("%Y%m%d")

    from services.shadow_weekly_service import weekly_report

    async def _run():
        from db import dispose_engine, initialize_database

        if args.init:
            ok, message = await initialize_database()
            if not ok:
                raise RuntimeError(f"schema init failed: {message}")
        try:
            return await weekly_report(start_date=start, end_date=end)
        finally:
            # aiosqlite worker threads must be stopped on the same loop, otherwise
            # the CLI process sits alive after the report is done (Windows).
            await dispose_engine()

    try:
        data = asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - CLI must fail clearly, not hang/stack-trace
        print(
            f"shadow weekly report failed: {type(exc).__name__}: {exc}\n"
            "If the ops DB is fresh, run once with --init (or start the backend "
            "with ENABLE_DB_PERSISTENCE=true) to create routing_decisions.",
            file=sys.stderr,
        )
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"shadow_weekly_{start}_{end}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    totals = data.get("totals") or {}
    print(
        "shadow weekly {start}-{end}: decisions={d} actual_linked={a} "
        "agreement={ag} rewrite={rw} hard_violations={hv} -> {path}".format(
            start=start,
            end=end,
            d=totals.get("decisions"),
            a=totals.get("actual_linked"),
            ag=totals.get("agreement_rate"),
            rw=totals.get("rewrite_rate"),
            hv=totals.get("hard_violations"),
            path=path,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
