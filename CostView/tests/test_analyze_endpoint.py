"""analyze 端点空结果语义 —— 筛选零匹配(200) 与 数据未就绪(503) 的区分。

背景（2026-09-21）：``build_tca_report`` 在「本次过滤条件命中 0 行」时同样置
``data_source_warning``，端点此前对该 warning 一律 503；叠加全局 5xx 遮蔽后，
用户按自己的条件筛不出数据时看到的是 "Internal server error"，被误导为
「数据未生成」。本用例锁定修正后的两种语义。
"""

from __future__ import annotations

import asyncio
from typing import Optional

import pytest
from fastapi import HTTPException

from CostView.api.routers import costview as r
from platform_data.contracts import TcaReport

_EMPTY_WARNING = (
    "tca_route_summary is empty — pipeline stage 5.5 has not yet run."
)


def _empty_report() -> TcaReport:
    """复刻 build_tca_report 零行分支的返回（含 warning）。"""
    return TcaReport(
        filters={"start_date": "20260918", "end_date": "20260918"},
        total_orders=0, offset=0, limit=50, orders=[],
        data_source_warning=_EMPTY_WARNING,
    )


def _patch_analytics(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: Optional[TcaReport],
    latest: Optional[str],
    has_data: bool = True,
) -> None:
    """以替身替换模块级查询服务，避免触碰真实数据目录。"""
    monkeypatch.setattr(r._analytics, "build_tca_report", lambda *a, **kw: report)
    monkeypatch.setattr(r._analytics, "get_latest_tca_date", lambda: latest)
    monkeypatch.setattr(r._analytics, "has_data_for_date", lambda _d: has_data)


def _request(**filters) -> r.TcaAnalyzeRequest:
    return r.TcaAnalyzeRequest(filters=r.TcaFilterPayload(**filters), limit=50)


def test_zero_match_returns_empty_report_not_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """库内有数据 + 过滤条件零命中 → 200 且 total_orders=0。"""
    _patch_analytics(monkeypatch, report=_empty_report(), latest="20260918")

    response = asyncio.run(r.analyze_tca(_request(broker="NOSUCH_BROKER"), None))

    assert response.success is True
    assert response.data is not None
    assert response.data["total_orders"] == 0
    assert "无匹配路由" in response.message
    assert "20260918" in response.message


def test_empty_table_still_503_data_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """库内完全无数据（表缺失/整表为空）→ 仍为 503 data_not_ready。"""
    _patch_analytics(monkeypatch, report=_empty_report(), latest=None)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(r.analyze_tca(_request(broker="NOSUCH_BROKER"), None))

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["code"] == "data_not_ready"
    assert excinfo.value.detail["message"] == _EMPTY_WARNING


def test_default_date_without_data_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """未显式过滤且默认日期（上一工作日）无数据 → 503 提示未生成。"""
    _patch_analytics(monkeypatch, report=None, latest="20260918", has_data=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(r.analyze_tca(_request(), None))

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["code"] == "data_not_ready"
    assert "数据尚未生成" in excinfo.value.detail["message"]


def test_non_empty_report_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常命中时保持原有文案（回归锚点）。"""
    report = TcaReport(
        filters={"start_date": "20260918", "end_date": "20260918"},
        total_orders=3, offset=0, limit=50, orders=[],
    )
    _patch_analytics(monkeypatch, report=report, latest="20260918")

    response = asyncio.run(r.analyze_tca(_request(broker="EQ-JPM"), None))

    assert response.data is not None
    assert response.data["total_orders"] == 3
    assert response.message == "TCA report: 3 routes matched"
