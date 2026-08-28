"""增量回填 tca_route_summary.fx_rate（CostView-Report 优化 ②）。

背景：tca_route_summary.fx_rate 由 S5.5 从 processed_fills 回填，但部分历史路由
在 tca 计算时尚无 fx_rate，导致该列 NULL（影响报告 USD 成交金额）。fill_bdib.fx_rate
为 fill 级权威源（报告期 CTE 同样按 fill_volume 加权取用），此处直接据此回填
tca_route_summary.fx_rate，无需重跑管道、无 Bloomberg 依赖。

口径：fx_rate = SUM(fill_volume * fx_rate) / NULLIF(SUM(fill_volume), 0)，按
(OrderId, RouteId, order_as_of_date) 聚合，与 report_aggregator._fbfx 一致。

幂等：仅更新当前 fx_rate IS NULL 且 fill_bdib 有 fx_rate 的路由；已回填的不变。
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_tca_fx_rate")

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402


def main() -> int:
    db = str(Config.FILL_BDIB_DB)
    T = Config.TCA_ROUTE_SUMMARY_TABLE
    conn = sqlite3.connect(db)
    try:
        before = conn.execute(f"SELECT COUNT(*) FROM {T} WHERE fx_rate IS NULL").fetchone()[0]
        # 仅回填 fill_bdib 有 fx_rate 来源的 NULL 路由
        conn.execute(f"""
            WITH src AS (
                SELECT OrderId, RouteId, order_as_of_date,
                       SUM(fill_volume * fx_rate) / NULLIF(SUM(fill_volume), 0) AS wfx
                FROM fill_bdib
                WHERE fx_rate IS NOT NULL
                GROUP BY OrderId, RouteId, order_as_of_date
            )
            UPDATE {T}
            SET fx_rate = src.wfx
            FROM src
            WHERE {T}.OrderId = src.OrderId
              AND {T}.RouteId = src.RouteId
              AND {T}.order_as_of_date = src.order_as_of_date
              AND {T}.fx_rate IS NULL
        """)
        after = conn.execute(f"SELECT COUNT(*) FROM {T} WHERE fx_rate IS NULL").fetchone()[0]
        still_no_src = conn.execute(
            f"""
            SELECT COUNT(*) FROM {T} t
            WHERE t.fx_rate IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM fill_bdib fb
                WHERE fb.OrderId = t.OrderId AND fb.RouteId = t.RouteId
                  AND fb.order_as_of_date = t.order_as_of_date AND fb.fx_rate IS NOT NULL
              )
            """
        ).fetchone()[0]
        conn.commit()
        logger.info("fx_rate 回填完成: 回填前 NULL=%d, 回填后 NULL=%d, 因 fill_bdib 无源仍 NULL=%d",
                    before, after, still_no_src)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
