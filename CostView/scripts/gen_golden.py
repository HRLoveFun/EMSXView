"""黄金样本生成器 — 从冻结的数据快照生成 TCA 回归基线。

用法（仓库根执行）：
    python CostView/scripts/gen_golden.py \
        --data-dir <冻结数据快照目录> \
        --start 20260901 --end 20260905 \
        --out CostView/tests/golden

生成 golden/<start>_<end>.json，内容为 filters + 逐路由关键指标期望值。
流程：对冻结快照生成 → 人工 review → 入库 tests/golden/。此后
test_golden_samples.py 以相对容差锁定指标，防止 SQL/口径改动导致
数值漂移（README §4.2「无黄金样本回归」整改）。

注意：必须使用冻结的数据快照副本（只读），不要指向生产数据目录——
生产数据每日更新会令 golden 基线失效。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 仓库根加入 sys.path（脚本可直接 python CostView/scripts/gen_golden.py 运行）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_access.storage.connection import AccessTier, ConnectionManager  # noqa: E402
from platform_data.contracts import TcaFilters  # noqa: E402

# 纳入黄金锁定的关键指标（金额类容差 1e-6，比率类放宽至 1e-4）
_RATIO_METRICS = {"par_rate", "arrival_cost_bps", "close_cost_bps",
                  "wagner_is_bps", "temp_impact_5min_bps",
                  "temp_impact_10min_bps", "temp_impact_30min_bps",
                  "perm_impact_bps"}


def _extract_route_metrics(route) -> dict:
    """从 TcaRouteSummary 提取纳入黄金锁定的字段。"""
    keys = [
        "fill", "route_shares", "par_rate", "p_avg", "p_arrival", "p_close",
        "p_decision", "arrival_cost_bps", "close_cost_bps", "opportunity_cost",
        "delay_cost", "trading_cost", "wagner_is", "wagner_is_bps",
        "temp_impact_5min_bps", "temp_impact_10min_bps",
        "temp_impact_30min_bps", "perm_impact_bps",
    ]
    out: dict = {}
    for k in keys:
        v = getattr(route, k, None)
        # 浮点统一转 float，None 保留（期望与实际均需 None 才算匹配）
        out[k] = float(v) if v is not None else None
    return out


def _tolerance_for(metric: str) -> float:
    """按指标类型返回相对容差。"""
    return 1e-4 if metric in _RATIO_METRICS else 1e-6


def build_case(data_dir: Path, start: str, end: str, max_routes: int) -> dict:
    """对冻结快照运行 TCA 报告并组装 golden case。"""
    overrides = {"fill_bdib": data_dir / "fill_bdib.db"}
    mgr = ConnectionManager(path_overrides=overrides)
    from CostView.src.tca_query_service import TcaQueryService
    svc = TcaQueryService(connection_manager=mgr)

    filters = TcaFilters(start_date=start, end_date=end,
                         aggregation="per_order", limit=max_routes, offset=0)
    report = svc.build_tca_report(filters, include_time_series=False)
    if report.data_source_warning:
        raise SystemExit(f"[ERROR] 快照数据不可用: {report.data_source_warning}")

    routes = {}
    for r in report.orders[:max_routes]:
        key = f"{r.OrderId}|{r.RouteId}|{r.order_as_of_date}"
        routes[key] = _extract_route_metrics(r)
    return {
        "input": {"start_date": start, "end_date": end, "aggregation": "per_order"},
        "total_routes": report.total_orders,
        "tolerances": {m: _tolerance_for(m)
                       for m in next(iter(routes.values()), {})},
        "expected": routes,
    }


def main() -> int:
    # Windows 控制台 cp1252 打印中文会 UnicodeEncodeError，强制 UTF-8
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="TCA 黄金样本生成器")
    parser.add_argument("--data-dir", required=True, type=Path,
                        help="冻结的数据快照目录（含 fill_bdib.db，只读）")
    parser.add_argument("--start", required=True, help="起始日 YYYYMMDD")
    parser.add_argument("--end", required=True, help="结束日 YYYYMMDD")
    parser.add_argument("--max-routes", type=int, default=200,
                        help="纳入基线的最大路由数")
    parser.add_argument("--out", type=Path,
                        default=Path("CostView/tests/golden"),
                        help="输出目录")
    args = parser.parse_args()

    case = build_case(args.data_dir, args.start, args.end, args.max_routes)
    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"{args.start}_{args.end}.json"
    out_file.write_text(
        json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"[OK] golden case 写入 {out_file} "
          f"({len(case['expected'])} routes, total={case['total_routes']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
