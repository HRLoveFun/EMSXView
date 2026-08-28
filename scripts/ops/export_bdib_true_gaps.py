"""导出 tca_route_summary 中 BDIB 真缺失路由清单（CostView-Report 优化 ①）。

判定：p_arrival IS NULL（该 ticker/date 连 Parquet 分区都无 BDIB bars）→ 真缺失。
拆分 scope：
- in_scope  = Exchange 在 Config.BDIB_EXCHANGE 白名单内 → 可经 BDIB 回补（真缺口）
- out_scope = 白名单外（CN/BZ/MM/DC/PW/IT/NZ/MUMBAI 等，2026-07-16 起设计排除）
             → 期望内 NULL，不应视为异常

输出 CSV：order_as_of_date, Exchange, equ_ticker, route_count, scope
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from collections import Counter
from pathlib import Path

logging_import = __import__("logging")
logger = logging_import.getLogger("export_bdib_gaps")

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
from DataPipeline.config import Config  # noqa: E402

OUT = Path(_ROOT) / "scripts" / "ops" / "_bdib_true_gaps.csv"


def main() -> None:
    wl = {str(e).strip().upper() for e in Config.BDIB_EXCHANGE if str(e).strip()}
    T = Config.TCA_ROUTE_SUMMARY_TABLE
    conn = sqlite3.connect(str(Config.FILL_BDIB_DB))
    rows = conn.execute(
        f"SELECT order_as_of_date, Exchange, equ_ticker, COUNT(*) AS n "
        f"FROM {T} WHERE p_arrival IS NULL "
        f"GROUP BY order_as_of_date, Exchange, equ_ticker "
        f"ORDER BY order_as_of_date, Exchange, equ_ticker"
    ).fetchall()
    conn.close()

    in_c, out_c = Counter(), Counter()
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_as_of_date", "Exchange", "equ_ticker", "route_count", "scope"])
        for d, ex, tk, n in rows:
            scope = "in_scope" if str(ex).upper() in wl else "out_scope"
            (in_c if scope == "in_scope" else out_c).update([ex])
            w.writerow([d, ex, tk, n, scope])

    print(f"真缺失路由组(唯一 date,exchange,ticker): {len(rows)}")
    print(f"  白名单内(真缺口,可回补): {sum(in_c.values())} 组  by_exch={dict(in_c.most_common())}")
    print(f"  范围外(设计排除,期望内): {sum(out_c.values())} 组  by_exch={dict(out_c.most_common())}")
    print(f"清单已写: {OUT}")


if __name__ == "__main__":
    main()
