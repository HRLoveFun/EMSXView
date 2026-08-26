"""回填 tca_route_summary.fx_rate 缺失行（L4c）。

背景（2026-08-26）：全量重算后 tca_route_summary 仍有 2741 行 fx_rate 为 NULL
（占 1.84%）。根因：processed_fills 与 fill_bdib 的 (OrderId, RouteId, mkt_timestamp)
key 历史不一致（S2→S5 管道历史数据问题），导致 S5.5 `_enrich_fills_with_fx_rate`
回填时部分行匹配不上。fill_bdib 层 fx_rate 完整（fx_null=0），是 fill 级权威源。

方案：对 tca_route_summary.fx_rate 缺失行，直接从 fill_bdib 按
(OrderId, RouteId, order_as_of_date) 做 fill_volume 加权聚合回填：
    agg_fx = SUM(fill_volume * fx_rate) / SUM(fill_volume)
口径已验证：正常日期 tca.fx_rate 与 fill_bdib 聚合值逐条一致（840/840），
fill_volume 加权与 S5.5 的 fill 量加权等价。

仅回填 fx_rate IS NULL 的行；fill_bdib 无源的极少数行（预计 ≤2）保持 NULL，
报告侧 `_fx_sum_sql` 对非 USD 缺汇率返回 NULL 安全降级，不产生虚高。

用法：
    # 备份 + 预览（推荐先跑）
    python scripts/ops/backfill_tca_route_fx.py --dry-run

    # 执行回填
    python scripts/ops/backfill_tca_route_fx.py

    # 按日期范围（缺省=全部 fx_rate 缺失行）
    python scripts/ops/backfill_tca_route_fx.py --start-date 20251101 --end-date 20260430
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import shutil
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_tca_route_fx")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _backup(db_path: Path) -> Path:
    """备份 fill_bdib.db（回填前的安全网）。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    backup = db_path.parent / "backups" / f"fill_bdib_pre_fxbackfill_{ts}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(db_path), str(backup))
    logger.info("已备份 fill_bdib.db -> %s", backup)
    return backup


def _build_where(start: str | None, end: str | None) -> tuple[str, list]:
    conds = ["fx_rate IS NULL"]
    params: list = []
    if start:
        conds.append("order_as_of_date >= ?")
        params.append(start)
    if end:
        conds.append("order_as_of_date <= ?")
        params.append(end)
    return " AND ".join(conds), params


def _count_targets(conn: sqlite3.Connection, where: str, params: list) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} WHERE {where}", params
    ).fetchone()
    return int(row[0])


def _backfill(conn: sqlite3.Connection, where: str, params: list) -> tuple[int, int]:
    """回填 fx_rate 缺失行；返回 (已回填数, 仍缺失数)。"""
    sql = f"""
        UPDATE {Config.TCA_ROUTE_SUMMARY_TABLE}
        SET fx_rate = (
            SELECT SUM(b.fill_volume * b.fx_rate) / NULLIF(SUM(b.fill_volume), 0)
            FROM fill_bdib b
            WHERE b.order_as_of_date = {Config.TCA_ROUTE_SUMMARY_TABLE}.order_as_of_date
              AND b.OrderId = {Config.TCA_ROUTE_SUMMARY_TABLE}.OrderId
              AND b.RouteId = {Config.TCA_ROUTE_SUMMARY_TABLE}.RouteId
              AND b.fx_rate IS NOT NULL
        )
        WHERE {where}
          AND EXISTS (
              SELECT 1 FROM fill_bdib b
              WHERE b.order_as_of_date = {Config.TCA_ROUTE_SUMMARY_TABLE}.order_as_of_date
                AND b.OrderId = {Config.TCA_ROUTE_SUMMARY_TABLE}.OrderId
                AND b.RouteId = {Config.TCA_ROUTE_SUMMARY_TABLE}.RouteId
                AND b.fx_rate IS NOT NULL
          )
    """
    cur = conn.execute(sql, params)
    conn.commit()
    filled = cur.rowcount
    still_null = _count_targets(conn, where, params)
    return filled, still_null


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 tca_route_summary.fx_rate 缺失行")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("--start-date", type=str, default=None, help="起始日期 YYYYMMDD")
    parser.add_argument("--end-date", type=str, default=None, help="结束日期 YYYYMMDD")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    args = parser.parse_args()

    db_path = Config.FILL_BDIB_DB
    where, params = _build_where(args.start_date, args.end_date)

    conn = sqlite3.connect(str(db_path))
    try:
        targets = _count_targets(conn, where, params)
        logger.info("待回填 fx_rate 缺失行数: %d%s", targets,
                    f"（范围 {args.start_date}~{args.end_date}）" if args.start_date or args.end_date else "")

        if args.dry_run:
            # 预览可填数（EXISTS 子查询统计）
            fillable = conn.execute(
                f"""
                SELECT COUNT(*) FROM {Config.TCA_ROUTE_SUMMARY_TABLE} t
                WHERE {where}
                  AND EXISTS (
                      SELECT 1 FROM fill_bdib b
                      WHERE b.order_as_of_date = t.order_as_of_date
                        AND b.OrderId = t.OrderId AND b.RouteId = t.RouteId
                        AND b.fx_rate IS NOT NULL
                  )
                """, params
            ).fetchone()[0]
            logger.info("DRY-RUN: 可回填 %d 行，剩余 %d 行保持 NULL（fill_bdib 无源）",
                        fillable, targets - fillable)
            return 0

        if not args.no_backup:
            _backup(db_path)

        filled, still_null = _backfill(conn, where, params)
        logger.info("回填完成: 已回填 %d 行，仍缺失 %d 行", filled, still_null)

        # 汇总校验
        row = conn.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END) "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE}"
        ).fetchone()
        logger.info("全局: total=%d fx_null=%d 非空率=%.2f%%",
                    row[0], row[1], (row[0] - row[1]) / row[0] * 100)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
