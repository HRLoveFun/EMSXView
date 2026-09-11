"""黄金样本回归 — 锁定 TCA 关键指标，防止 SQL/口径改动导致数值漂移。

运行前提（二选一，缺一则整组 skip，不影响常规 CI）：
1. 存在 tests/golden/*.json 基线（由 CostView/scripts/gen_golden.py 生成）；
2. 环境变量 EMSXVIEW_GOLDEN_DATA_DIR 指向与基线同源的**冻结数据快照目录**
   （含 fill_bdib.db，只读）。

警示：不要把该 env 指向生产数据目录——生产数据每日更新，会使基线失效。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
_GOLDEN_DATA_DIR = os.getenv("EMSXVIEW_GOLDEN_DATA_DIR", "")

pytestmark = pytest.mark.skipif(
    not _GOLDEN_DIR.is_dir() or not any(_GOLDEN_DIR.glob("*.json")),
    reason="无 golden 基线 (tests/golden/*.json)，先运行 scripts/gen_golden.py",
)

_case_files = sorted(_GOLDEN_DIR.glob("*.json")) if _GOLDEN_DIR.is_dir() else []


@pytest.mark.skipif(not _GOLDEN_DATA_DIR, reason="未设置 EMSXVIEW_GOLDEN_DATA_DIR")
@pytest.mark.parametrize("case_file", _case_files)
def test_golden_case(case_file: Path, tmp_path: Path):
    """重算 golden case 并以相对容差逐指标比对。"""
    from data_access.storage.connection import AccessTier, ConnectionManager
    from platform_data.contracts import TcaFilters
    from CostView.src.tca_query_service import TcaQueryService

    case = json.loads(case_file.read_text(encoding="utf-8"))
    overrides = {"fill_bdib": Path(_GOLDEN_DATA_DIR) / "fill_bdib.db"}
    mgr = ConnectionManager(path_overrides=overrides)
    svc = TcaQueryService(connection_manager=mgr)

    inp = case["input"]
    filters = TcaFilters(
        start_date=inp["start_date"], end_date=inp["end_date"],
        aggregation=inp.get("aggregation", "per_order"),
        limit=len(case["expected"]), offset=0,
    )
    report = svc.build_tca_report(filters, include_time_series=False)
    assert not report.data_source_warning, (
        f"{case_file.name}: 冻结快照不可用 — {report.data_source_warning}"
    )

    actual = {
        f"{r.OrderId}|{r.RouteId}|{r.order_as_of_date}": r
        for r in report.orders
    }
    tolerances = case.get("tolerances", {})
    for key, expected_metrics in case["expected"].items():
        route = actual.get(key)
        assert route is not None, f"{case_file.name}: 路由 {key} 在重算结果中缺失"
        for metric, exp in expected_metrics.items():
            act = getattr(route, metric, None)
            tol = tolerances.get(metric, 1e-6)
            assert act == pytest.approx(exp, rel=tol, abs=1e-12), (
                f"{case_file.name}: 路由 {key} 指标 {metric!r} 漂移 "
                f"expected={exp} actual={act} (rel_tol={tol})"
            )
