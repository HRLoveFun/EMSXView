"""临时运行 S7 CalculateDailyMetricsStage 补跑 daily_close（003-tca-core-benchmarks）。

用法:
    python scripts/ops/backfill_daily_metrics.py --dates 20260810 20260811 20260812
    python scripts/ops/backfill_daily_metrics.py --start-date 20260501 --end-date 20260812
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
_EMSX_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config
from DataPipeline.orchestration.context import PipelineContext
from DataPipeline.orchestration.stages_process import CalculateDailyMetricsStage
from DataPipeline.storage.schema.inline_ddl import init_raw_bdib_schema

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_daily_metrics")


def _resolve_dates(start: Optional[str], end: Optional[str]) -> list[str]:
    """从 processed_fills 提取日期范围（YYYYMMDD）。"""
    import sqlite3
    conn = sqlite3.connect(str(Config.PROCESSED_FILLS_DB))
    try:
        sql = (
            "SELECT DISTINCT order_as_of_date FROM processed_fills "
            "WHERE order_as_of_date IS NOT NULL"
        )
        params: list = []
        if start:
            sql += " AND order_as_of_date >= ?"
            params.append(start)
        if end:
            sql += " AND order_as_of_date <= ?"
            params.append(end)
        sql += " ORDER BY order_as_of_date"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


def main() -> int:
    parser = argparse.ArgumentParser(description="S7 daily metrics 补跑")
    parser.add_argument("--dates", nargs="+", help="指定日期列表 YYYYMMDD")
    parser.add_argument("--start-date", help="开始日期")
    parser.add_argument("--end-date", help="结束日期")
    args = parser.parse_args()

    if args.dates:
        dates = [d.strip() for d in args.dates if d.strip()]
    else:
        dates = _resolve_dates(args.start_date, args.end_date)

    if not dates:
        logger.error("无待处理日期")
        return 1

    logger.info("S7 补跑日期数: %d (首个 %s .. 末尾 %s)", len(dates), dates[0], dates[-1])

    ctx = PipelineContext(target_dates=dates, force=True, config={})
    stage = CalculateDailyMetricsStage()
    ok = stage.execute(ctx)

    summary = ctx.summary.get("daily_metrics", {})
    logger.info("执行完成: ok=%s, summary=%s", ok, summary)
    logger.info("错误数: %d", len(ctx.errors))
    if ctx.errors:
        for err in ctx.errors[:5]:
            logger.error("  - %s: %s", err["stage"], err["error"])
    return 0 if ok and ctx.is_successful else 1


if __name__ == "__main__":
    sys.exit(main())
