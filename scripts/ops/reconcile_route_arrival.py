"""路由到达价对账 CLI —— 057 DL-12/063（只读）。

上游值（``tca_route_summary.p_route_arrival``，EMSXDataPipeline 物化）与本侧
自给值逐路由对账：差异 <1bp 的占比 ≥99% 方可通过（tasks.md DL-12 检验方法）。

用法：
    python scripts/ops/reconcile_route_arrival.py [--start YYYYMMDD] [--end YYYYMMDD]

    --start/--end   对账日期范围（YYYYMMDD）；默认取本机日期前一天的单日

输出：JSON 报告（compared / within_1bp / pct_within_1bp / max_diff_bps /
over_tolerance_examples + 自给覆盖率），供切换门禁与计划任务告警接线。

退出码：0 = 上游未就绪（仅披露自给覆盖率）或对账通过；1 = 对账低于阈值
（或上游列存在但无比对样本——不得盲切 L1）。

口径与切换操作约定见 ``CostView/src/monitoring/route_arrival.py`` docstring：
上游列就绪 + 本脚本退出码 0 后，消费方（DL-19/DL-20）经 ``resolve_arrival_fields``
完成 L1 切换；跨日/盘前下达行（取当日首 bar open）的差异需人工核对后再计入。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# ── 路径设置（脚本直接运行时需要仓库根）──
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from CostView.src.monitoring.route_arrival import (  # noqa: E402
    RECONCILE_MIN_PCT,
    arrival_coverage,
    build_route_arrival_context,
    load_upstream_arrival,
    reconcile_arrival,
)
from data_access.config import Config  # noqa: E402
from data_access.storage.connection import AccessTier, ConnectionManager  # noqa: E402

logger = logging.getLogger(__name__)


def _default_date() -> str:
    """默认对账日期：本机日期前一天（与日更产物就绪时点错开一日）。"""
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def load_route_stubs(mgr: ConnectionManager, start_date: str, end_date: str) -> list[SimpleNamespace]:
    """从 ``tca_route_summary`` 取对账范围内的路由桩（标识列 + equ_ticker）。

    读该表而非 processed_fills：汇总表即路由全集，且自带 equ_ticker。
    """
    conn = mgr.get_connection("fill_bdib", AccessTier.READ)
    try:
        rows = conn.execute(
            f"SELECT OrderId, RouteId, order_as_of_date, equ_ticker "
            f"FROM {Config.TCA_ROUTE_SUMMARY_TABLE} "
            f"WHERE order_as_of_date BETWEEN ? AND ?",
            [start_date, end_date],
        ).fetchall()
    finally:
        conn.close()
    return [
        SimpleNamespace(OrderId=row[0], RouteId=row[1], order_as_of_date=row[2], equ_ticker=row[3])
        for row in rows
    ]


def run_reconcile(mgr: ConnectionManager, start_date: str, end_date: str) -> dict[str, Any]:
    """对账主流程：上游列 vs 本侧自给，返回 JSON 可序列化报告。"""
    routes = load_route_stubs(mgr, start_date, end_date)
    upstream = load_upstream_arrival(mgr, start_date, end_date)
    ctx = build_route_arrival_context(mgr, routes, start_date, end_date)
    report: dict[str, Any] = {
        "start": start_date,
        "end": end_date,
        "upstream_ready": bool(upstream),
        "reconcile": reconcile_arrival(
            {key: value["p_route_arrival"] for key, value in upstream.items()},
            {key: value.p_route_arrival for key, value in ctx.items()},
        ),
        "selfsup_coverage": arrival_coverage(routes, ctx),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="路由到达价对账（057 DL-12/063）")
    parser.add_argument("--start", default="", help="起始日期 YYYYMMDD（默认前一天）")
    parser.add_argument("--end", default="", help="结束日期 YYYYMMDD（默认同 start）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    start_date = args.start or _default_date()
    end_date = args.end or start_date
    mgr = ConnectionManager()
    try:
        report = run_reconcile(mgr, start_date, end_date)
    except Exception as exc:
        logger.error("对账失败: %s", exc)
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not report["upstream_ready"]:
        logger.info("上游未就绪（tca_route_summary 无 p_route_arrival 列）——仅披露自给覆盖率")
        return 0
    pct = report["reconcile"]["pct_within_1bp"]
    if pct is not None and pct >= RECONCILE_MIN_PCT:
        logger.info("对账通过：%.2f%% ≥ %.1f%%，可切换 L1", pct, RECONCILE_MIN_PCT)
        return 0
    logger.error("对账未通过：pct_within_1bp=%s（阈值 %.1f%%），不得切换 L1", pct, RECONCILE_MIN_PCT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
