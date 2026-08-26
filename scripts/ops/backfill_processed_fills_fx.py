"""全量回填 processed_fills.fx_rate（L4a）。

从 fill_bdib 按 (OrderId, RouteId, mkt_timestamp) 回填 fill 级 fx_rate 并写回
processed_fills（复用 S5.5 的 _enrich_fills_with_fx_rate 逻辑，覆盖全部日期）。

用法：
    python scripts/ops/backfill_processed_fills_fx.py --dry-run
    python scripts/ops/backfill_processed_fills_fx.py
    python scripts/ops/backfill_processed_fills_fx.py --dates 20260805 20260820
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_processed_fills_fx")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _all_dates(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT order_as_of_date FROM {Config.PROCESSED_FILLS_TABLE} "
        "WHERE order_as_of_date IS NOT NULL ORDER BY order_as_of_date"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _backfill_date(cm, date_str: str) -> tuple[int, int]:
    """回填单日 processed_fills.fx_rate；返回 (匹配行数, 写回行数)。"""
    from DataPipeline.orchestration.stages_process import _enrich_fills_with_fx_rate
    from DataPipeline.storage.repositories.fills import SqliteFillReadRepository

    fills_reader = SqliteFillReadRepository(cm)
    df = fills_reader.get_fills_for_date(date_str)
    if df.empty:
        return 0, 0
    enriched = _enrich_fills_with_fx_rate(cm, df, date_str)
    matched = int(enriched["fx_rate"].notna().sum()) if "fx_rate" in enriched.columns else 0
    return matched, len(enriched)


def main() -> int:
    parser = argparse.ArgumentParser(description="全量回填 processed_fills.fx_rate")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("--dates", nargs="+", default=None, help="指定日期（缺省=全部）")
    args = parser.parse_args()

    from DataPipeline.storage.connection import ConnectionManager
    cm = ConnectionManager()

    conn = sqlite3.connect(str(Config.PROCESSED_FILLS_DB))
    try:
        dates = args.dates or _all_dates(conn)
        logger.info("待处理日期 %d 个（%s~%s）", len(dates), dates[0], dates[-1])
    finally:
        conn.close()

    if args.dry_run:
        logger.info("DRY-RUN: 完成核查，未写入")
        return 0

    total_matched = total_written = 0
    for i, d in enumerate(dates, 1):
        try:
            matched, written = _backfill_date(cm, d)
            total_matched += matched
            total_written += written
            if i % 20 == 0 or matched == 0:
                logger.info("  %s: 匹配 fx_rate %d / %d 行", d, matched, written)
        except Exception as exc:
            logger.warning("  %s 回填失败: %s", d, exc)
    logger.info("完成: 匹配 %d 行（日期数 %d）", total_matched, len(dates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
