"""CCP-20261112-sqlite.tca_route_summary — 跨层契约镜像（后端侧）。

上游在两列上的收口口径要求下游用 ``pytest backend/api/tests -k contract``
证明已接入。CostView 侧的临时 SQLite 行为测试见
``CostView/tests/test_tca_route_summary_contract.py``；本文件只锁跨层形状：

1. ``TcaRouteSummary`` 暴露 ``adv_20d`` / ``daily_volatility``，默认 ``None``；
2. API 序列化原样下发 ``None``（不填 0），字段名与上游契约一致。
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from CostView.api.routers.costview import _serialize_route  # noqa: E402
from platform_data.contracts import TcaRouteSummary  # noqa: E402

_CONTRACT_COLUMNS = ("adv_20d", "daily_volatility")


def _empty_route() -> TcaRouteSummary:
    """所有字段置 None 的路由对象；只用于验证 serialize 的缺失语义。"""
    return TcaRouteSummary(**{f.name: None for f in fields(TcaRouteSummary)})


def test_contract_columns_exist_with_none_default() -> None:
    field_map = {f.name: f for f in fields(TcaRouteSummary)}
    for column in _CONTRACT_COLUMNS:
        assert column in field_map, f"TcaRouteSummary 缺少契约列 {column}"
        assert field_map[column].default is None, f"{column} 默认值必须为 None"


def test_serializer_preserves_missing_as_null() -> None:
    payload = _serialize_route(_empty_route())

    for column in _CONTRACT_COLUMNS:
        assert column in payload, f"API payload 缺少契约列 {column}"
        assert payload[column] is None
        assert payload[column] != 0


def test_serializer_keeps_null_distinct_from_zero() -> None:
    route = _empty_route()
    route.adv_20d = None
    route.daily_volatility = 0.0

    payload = _serialize_route(route)

    assert payload["adv_20d"] is None
    assert payload["daily_volatility"] == 0.0
    assert payload["adv_20d"] != payload["daily_volatility"]
