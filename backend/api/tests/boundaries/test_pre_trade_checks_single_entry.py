"""A02 架构守卫：pre_trade_checks 是下单前检查的唯一入口。

除 `services/pre_trade_checks.py` 外，业务代码不得直接调用：
`evaluate_access` / `evaluate_order_compliance` / `validate_route_submission`。
（`compliance_service.check_route` 仍被 batch-modify 用于改单，不在此列。）
"""

from __future__ import annotations

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {API_ROOT / "services" / "pre_trade_checks.py"}
TARGETS = {"evaluate_access", "evaluate_order_compliance", "validate_route_submission"}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _offenders() -> list[str]:
    found: list[str] = []
    for path in API_ROOT.rglob("*.py"):
        if "tests" in path.parts or path in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node.func) in TARGETS:
                found.append(f"{path.relative_to(API_ROOT)}:{node.lineno}:{_call_name(node.func)}")
    return found


def test_no_direct_pre_trade_check_calls():
    """禁止绕过 pre_trade_checks 直接执行分层检查。"""
    assert _offenders() == []
