"""增量回填 tca_route_summary.perm_impact_bps（CostView-Report 优化 ⑥）。

背景：perm_impact_bps 依赖「下一交易日 bdib_daily_summary.daily_close」（跨日恢复
窗口，Almgren & Chriss 1999 / Obizhaeva & Wang 2013）。S7 daily_close 未覆盖到
某些下一交易日时，该指标为 NULL。此处直接据已有次日 daily_close 重算：

    perm_impact_bps = (next_close / p_arrival - 1) * side_sign * 10000
    side_sign: Buy=-1, Sell=+1（与 tca_route_metrics._pnl_side_sign 一致）

分层处理：
- 次日 daily_close 已存在 → 直接 UPDATE 重算（无需 Bloomberg）。
- 次日 daily_close 缺失 → 收集 (equ_ticker, order_as_of_date, next_trade_date)
  写入 CSV，供用户跑 S7 daily_close 补跑后再次运行本脚本。

幂等：仅更新 perm_impact_bps IS NULL 且可计算（p_arrival 非空 + 次日 close 非空）的路由。
bdib_daily_summary 位于 raw_bdib.db，此处 ATTACH 后跨库计算。
"""
from __future__ import annotations

import csv
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_perm_impact")

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402


def _next_day_sql(table: str) -> str:
    return (
        "SELECT MIN(trade_date) FROM rb.bdib_daily_summary x "
        "WHERE x.equ_ticker = {tbl}.equ_ticker AND x.trade_date > {tbl}.order_as_of_date"
    ).format(tbl=table)


def main() -> int:
    db = str(Config.FILL_BDIB_DB)
    T = Config.TCA_ROUTE_SUMMARY_TABLE
    conn = sqlite3.connect(db)
    conn.execute(f"ATTACH DATABASE '{Config.RAW_BDIB_DB}' AS rb")
    try:
        before = conn.execute(
            f"SELECT COUNT(*) FROM {T} WHERE perm_impact_bps IS NULL"
        ).fetchone()[0]

        # ── 第一层：次日 daily_close 已存在 → 直算 ──
        nd_sql = _next_day_sql(T)
        update_sql = """
            UPDATE {tbl}
            SET perm_impact_bps = (nd.daily_close / {tbl}.p_arrival - 1.0)
                                 * CASE WHEN {tbl}.Side = 'B' THEN -1
                                        WHEN {tbl}.Side = 'S' THEN 1 ELSE 0 END
                                 * 10000.0
            FROM rb.bdib_daily_summary nd
            WHERE {tbl}.perm_impact_bps IS NULL
              AND {tbl}.p_arrival IS NOT NULL AND {tbl}.p_arrival <> 0
              AND nd.equ_ticker = {tbl}.equ_ticker
              AND nd.trade_date = ({next_day})
              AND nd.daily_close IS NOT NULL
        """.format(tbl=T, next_day=nd_sql)
        conn.execute(update_sql)
        after = conn.execute(
            "SELECT COUNT(*) FROM {tbl} WHERE perm_impact_bps IS NULL".format(tbl=T)
        ).fetchone()[0]
        recomputed = before - after
        logger.info("perm_impact_bps 第一层重算: 回填前 NULL=%d, 本层重算=%d, 剩余 NULL=%d",
                    before, recomputed, after)

        # ── 第二层：收集仍需次日 daily_close 的路由 → CSV ──
        pending_sql = """
            SELECT DISTINCT {tbl}.equ_ticker, {tbl}.order_as_of_date,
                   ({next_day}) AS next_trade_date
            FROM {tbl}
            WHERE {tbl}.perm_impact_bps IS NULL
              AND {tbl}.p_arrival IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM rb.bdib_daily_summary nd
                WHERE nd.equ_ticker = {tbl}.equ_ticker
                  AND nd.trade_date = ({next_day})
                  AND nd.daily_close IS NOT NULL
              )
        """.format(tbl=T, next_day=nd_sql)
        pending = conn.execute(pending_sql).fetchall()
        out = Path(_ROOT) / "scripts" / "ops" / "_perm_impact_pending_s7.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["equ_ticker", "order_as_of_date", "next_trade_date"])
            for tk, oad, nd in pending:
                w.writerow([tk, oad, nd if nd is not None else "NO_NEXT_DATE"])
        logger.info("待 S7 daily_close 补跑的路由组: %d 组，清单已写 %s", len(pending), out)
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
