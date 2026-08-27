"""P2 健壮性机制回归测试（M2.1 守恒 / M6.1 health_check 逻辑检查 / M5.2 体积增长）。

路径：DataPipeline/tests/guardrail/test_pipeline_resilience_p2.py
对应设计：docs/spec/pipeline-resilience.md
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]  # .../EMSXView
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_conservation():
    return _load(
        "cross_db_conservation_ut",
        _ROOT / "DataPipeline" / "pipeline_guards" / "cross_db_conservation.py",
    )


def _load_health_check():
    return _load(
        "health_check_ut",
        _ROOT / "scripts" / "health_check.py",
    )


def test_conservation_clean_when_balanced():
    """M2.1：上游/下游同日行数均衡时无缺失。"""
    mod = _load_conservation()
    counts = {
        "20260825": {"raw_fills": 100, "processed_fills": 100, "raw_bdib": 50, "fill_bdib": 50},
        "20260826": {"raw_fills": 80, "processed_fills": 80, "raw_bdib": 40, "fill_bdib": 40},
    }
    res = mod.audit_conservation(per_date_counts=counts)
    assert res["ok"] is True
    assert res["gaps"] == []


def test_conservation_flags_missing_downstream():
    """M2.1：上游有行但下游整日 0 行必须标记缺失（A1/A3 类）。"""
    mod = _load_conservation()
    counts = {
        "20260825": {"raw_fills": 100, "processed_fills": 0, "raw_bdib": 50, "fill_bdib": 50},
        "20260826": {"raw_fills": 80, "processed_fills": 80, "raw_bdib": 40, "fill_bdib": 0},
    }
    res = mod.audit_conservation(per_date_counts=counts)
    assert res["ok"] is False
    pairs = {g["pair"] for g in res["gaps"]}
    assert "raw_fills->processed_fills" in pairs
    assert "raw_bdib->fill_bdib" in pairs


def test_health_check_logical_methods_return_dicts():
    """M6.1/M5.2：新增逻辑检查项均返回 dict 且不抛异常。"""
    hc = _load_health_check()
    checker = hc.HealthChecker(quick=True)
    for method in (
        "_check_freshness",
        "_check_shell_tables",
        "_check_exchange_diff",
        "_check_volume_growth",
        "_check_conservation",
    ):
        result = getattr(checker, method)()
        assert isinstance(result, dict)
        assert "alert" in result


def test_health_check_run_includes_logical_checks():
    """M6.1/M5.2：run() 注册并产出逻辑检查项。"""
    hc = _load_health_check()
    results = hc.HealthChecker(quick=True).run()
    for name in ("freshness", "shell_tables", "exchange_diff", "volume_growth"):
        assert name in results["checks"], f"{name} 未注册"
