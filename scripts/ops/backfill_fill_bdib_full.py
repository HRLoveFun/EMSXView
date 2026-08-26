"""fill_bdib 全量修复（L3）。

两个步骤：
1. 补 ccy_ticker：所有 ccy_ticker 缺失的日期（40 个）。
   补源优先级：
   a. agg_fills_10s（processed_fills.db）按 (OrderId, RouteId, mkt_timestamp) —— 覆盖大多数日期
   b. route_registry（L2 已重建）按 (OrderId, RouteId) —— 覆盖 agg 也缺失的日期
      （20260408 / 20260805 / 20260824 等）
2. 全量重算 fx_rate：fill_bdib 全部日期。
   - UPPER(TRIM(ccy_ticker)) = 'USD CURNCY' → 1.0
   - 复合币种 → 查 fx_rates 表（按规范化 ccy_ticker + order_as_of_date）
   - NULL/未知 → NULL（不置 1.0，避免汇率缺失时数量级虚高）

用法：
    python scripts/ops/backfill_fill_bdib_full.py --dry-run
    python scripts/ops/backfill_fill_bdib_full.py
    python scripts/ops/backfill_fill_bdib_full.py --dates 20260805 20260408 20260824
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_fill_bdib_full")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _missing_ccy_dates(fb: sqlite3.Connection) -> list[str]:
    """fill_bdib 中 ccy_ticker 缺失的日期列表。"""
    rows = fb.execute(
        "SELECT DISTINCT order_as_of_date FROM fill_bdib "
        "WHERE ccy_ticker IS NULL OR TRIM(ccy_ticker) = '' ORDER BY order_as_of_date"
    ).fetchall()
    return [str(r[0]) for r in rows]


def _backfill_from_agg(fb: sqlite3.Connection, pf: sqlite3.Connection, date_str: str) -> int:
    """从 agg_fills_10s 按 (OrderId, RouteId, mkt_timestamp) 回填 ccy_ticker。"""
    agg = pf.execute(
        f"SELECT OrderId, RouteId, mkt_timestamp, ccy_ticker FROM {Config.AGG_10S_TABLE} "
        "WHERE order_as_of_date = ? AND ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != ''",
        (date_str,),
    ).fetchall()
    if not agg:
        return 0
    fb.execute("BEGIN")
    updated = 0
    for order_id, route_id, mkt_ts, ccy in agg:
        cur = fb.execute(
            "UPDATE fill_bdib SET ccy_ticker = ? "
            "WHERE OrderId = ? AND RouteId = ? AND mkt_timestamp = ? AND order_as_of_date = ? "
            "AND (ccy_ticker IS NULL OR TRIM(ccy_ticker) = '')",
            (str(ccy), str(order_id), str(route_id), str(mkt_ts), date_str),
        )
        updated += cur.rowcount
    fb.commit()
    return updated


def _backfill_from_registry(fb: sqlite3.Connection, registry_conn: sqlite3.Connection, date_str: str) -> int:
    """从 route_registry 按 (OrderId, RouteId) 回填 ccy_ticker（agg 缺失时兜底）。

    注意：route_registry 是分区表，存于 execution_history.db（Config.EXECUTION_HISTORY_DB），
    由调用方传入 registry_conn；fill_bdib 路由集合从 fb 连接查（fill_bdib.db）。
    """
    routes = fb.execute(
        "SELECT DISTINCT OrderId, RouteId FROM fill_bdib WHERE order_as_of_date = ? "
        "AND (ccy_ticker IS NULL OR TRIM(ccy_ticker) = '')",
        (date_str,),
    ).fetchall()
    if not routes:
        return 0
    fb.execute("BEGIN")
    updated = 0
    for oid, rid in routes:
        row = registry_conn.execute(
            "SELECT ccy_ticker FROM route_registry WHERE OrderId = ? AND RouteId = ? "
            "AND ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != ''",
            (str(oid), str(rid)),
        ).fetchone()
        if row is None:
            continue
        cur = fb.execute(
            "UPDATE fill_bdib SET ccy_ticker = ? "
            "WHERE OrderId = ? AND RouteId = ? AND order_as_of_date = ? "
            "AND (ccy_ticker IS NULL OR TRIM(ccy_ticker) = '')",
            (str(row[0]), str(oid), str(rid), date_str),
        )
        updated += cur.rowcount
    fb.commit()
    return updated


def _recompute_fx_rate(fb: sqlite3.Connection, date_str: str) -> int:
    """重算 fill_bdib.fx_rate（USD→1.0；复合币种查 fx_rates；未知→NULL）。"""
    cur = fb.execute(
        f"""
        UPDATE fill_bdib
        SET fx_rate = CASE
            WHEN UPPER(TRIM(ccy_ticker)) = 'USD CURNCY' THEN 1.0
            WHEN ccy_ticker IS NULL OR TRIM(ccy_ticker) = '' THEN NULL
            ELSE (
                SELECT f.fx_rate FROM {Config.FX_RATES_TABLE} f
                WHERE f.ccy_ticker = UPPER(TRIM(fill_bdib.ccy_ticker))
                  AND f.order_as_of_date = fill_bdib.order_as_of_date
            )
        END
        WHERE order_as_of_date = ?
        """,
        (date_str,),
    )
    fb.commit()
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description="fill_bdib 全量修复：补 ccy_ticker + 重算 fx_rate")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("--dates", nargs="+", default=None,
                        help="指定日期（缺省=全部 ccy_ticker 缺失日期）")
    args = parser.parse_args()

    fb_path = Config.FILL_BDIB_DB
    pf_path = Config.PROCESSED_FILLS_DB
    eh_path = Config.EXECUTION_HISTORY_DB
    fb = sqlite3.connect(str(fb_path))
    pf = sqlite3.connect(str(pf_path))
    registry_conn = sqlite3.connect(str(eh_path))
    try:
        dates = args.dates or _missing_ccy_dates(fb)
        logger.info("待处理日期 %d 个: %s", len(dates), dates[:10] + (["..."] if len(dates) > 10 else []))

        if args.dry_run:
            logger.info("DRY-RUN: 完成核查，未写入")
            return 0

        for d in dates:
            n1 = _backfill_from_agg(fb, pf, d)
            n2 = _backfill_from_registry(fb, registry_conn, d)
            # 汇总该日现状（fx_rate 尚未重算，仅展示 ccy_ticker 修复结果）
            row = fb.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN ccy_ticker IS NULL OR TRIM(ccy_ticker)='' THEN 1 ELSE 0 END) "
                "FROM fill_bdib WHERE order_as_of_date = ?",
                (d,),
            ).fetchone()
            logger.info(
                "%s: agg回填=%d registry回填=%d | total=%s ccy_null=%s",
                d, n1, n2, row[0], row[1],
            )
    finally:
        fb.close()
        pf.close()
        registry_conn.close()

    # 全量 fx_rate 重算（覆盖全部日期，修正早期 1.0 残留 + 已补 ccy 日期）
    logger.info("全量重算 fx_rate（全部日期）...")
    fb = sqlite3.connect(str(fb_path))
    try:
        total = 0
        for d in _all_dates(fb):
            total += _recompute_fx_rate(fb, d)
        logger.info("全量 fx_rate 重算完成: %d 行", total)
    finally:
        fb.close()
    return 0


def _all_dates(fb: sqlite3.Connection) -> list[str]:
    rows = fb.execute("SELECT DISTINCT order_as_of_date FROM fill_bdib ORDER BY order_as_of_date").fetchall()
    return [str(r[0]) for r in rows]


if __name__ == "__main__":
    sys.exit(main())
