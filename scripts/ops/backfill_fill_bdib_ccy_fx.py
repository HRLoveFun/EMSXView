"""一次性回补脚本：修复 fill_bdib.ccy_ticker 与 fx_rate。

背景（2026-08-25，KS 市场 16.74B 数量级问题根因链）：
- fill_bdib 部分日期（20260805、20260817~21）ccy_ticker 全 NULL，
  导致 S5 集成阶段按 (order_as_of_date, ccy_ticker) merge fx_rates 失败；
- 旧版 usd_mask 用 str.contains("USD") 会把 "USDKRW Curncy" 等复合币种
  误判为 USD 置 1.0（本次已随代码修复，此处重算存量数据）。

步骤（仅影响 ccy_ticker 缺失日期）：
1. 从 agg_fills_10s（processed_fills.db）按 (OrderId, RouteId, mkt_timestamp)
   回填 fill_bdib.ccy_ticker；
2. 重算 fill_bdib.fx_rate：
   - 规范化 ccy_ticker = 'USD CURNCY' → 1.0
   - 复合币种 → 从 fx_rates 表按 (ccy_ticker, order_as_of_date) 取值
   - NULL/未知 → NULL（不置 1.0，避免汇率缺失时数量级虚高）

用法：
    python scripts/ops/backfill_fill_bdib_ccy_fx.py --dry-run
    python scripts/ops/backfill_fill_bdib_ccy_fx.py
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
logger = logging.getLogger("backfill_fill_bdib_ccy_fx")

_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_ROOT))

from DataPipeline.config import Config  # noqa: E402

#: ccy_ticker 全 NULL 的目标日期（从数据核查确认）
TARGET_DATES = ["20260805", "20260817", "20260818", "20260819", "20260820", "20260821"]


def _conn(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(path))


def _backfill_ccy_ticker(fb: sqlite3.Connection, pf: sqlite3.Connection, date_str: str) -> int:
    """从 agg_fills_10s 回填 fill_bdib.ccy_ticker，返回更新行数。"""
    agg = pf.execute(
        f"""
        SELECT OrderId, RouteId, mkt_timestamp, ccy_ticker
        FROM {Config.AGG_10S_TABLE}
        WHERE order_as_of_date = ? AND ccy_ticker IS NOT NULL AND TRIM(ccy_ticker) != ''
        """,
        (date_str,),
    ).fetchall()
    if not agg:
        logger.warning("  %s: agg_fills_10s 无 ccy_ticker 可回填", date_str)
        return 0
    # 逐行 UPDATE（10s 桶与 fill_bdib 一一对应）
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


def _recompute_fx_rate(fb: sqlite3.Connection, date_str: str) -> int:
    """重算 fill_bdib.fx_rate（USD→1.0；复合币种查 fx_rates 表；未知→NULL）。"""
    sql = f"""
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
    """
    cur = fb.execute(sql, (date_str,))
    fb.commit()
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description="回补 fill_bdib ccy_ticker + fx_rate")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不写入")
    parser.add_argument("--dates", nargs="+", default=TARGET_DATES,
                        help="目标日期（缺省为核查确认的 ccy_ticker 缺失日期）")
    args = parser.parse_args()

    fb_path = Config.FILL_BDIB_DB
    pf_path = Config.PROCESSED_FILLS_DB
    if args.dry_run:
        logger.info("DRY-RUN: 将处理日期 %s", args.dates)
        logger.info("  fill_bdib       : %s", fb_path)
        logger.info("  processed_fills : %s", pf_path)
        return 0

    fb = _conn(fb_path)
    pf = _conn(pf_path)
    try:
        for d in args.dates:
            logger.info("处理 %s:", d)
            n_ccy = _backfill_ccy_ticker(fb, pf, d)
            logger.info("  ccy_ticker 回填: %d 行", n_ccy)
            n_fx = _recompute_fx_rate(fb, d)
            logger.info("  fx_rate 重算: %d 行", n_fx)
    finally:
        fb.close()
        pf.close()

    # 汇总校验
    fb = _conn(fb_path)
    try:
        for d in args.dates:
            row = fb.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN ccy_ticker IS NULL OR TRIM(ccy_ticker)='' THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN fx_rate IS NULL THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN fx_rate = 1.0 THEN 1 ELSE 0 END) "
                "FROM fill_bdib WHERE order_as_of_date = ?",
                (d,),
            ).fetchone()
            logger.info(
                "  校验 %s: total=%s ccy_null=%s fx_null=%s fx_one=%s",
                d, row[0], row[1], row[2], row[3],
            )
    finally:
        fb.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
