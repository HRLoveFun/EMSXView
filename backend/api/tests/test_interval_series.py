"""057 DL-30 — 执行区间量价服务与端点测试。

覆盖：桶网格（末桶截断/非法参数）、聚合（VWAP/累计量/显式 gap）、
数据源优先级（盘中库 > 正式库 > none）、端点参数校验。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from routers import interval_series as router_module  # noqa: E402
from services import interval_series as svc  # noqa: E402


class FakeReader:
    """盘中库读侧替身：可按需返回 bar 或无数据。"""

    def __init__(self, bars: list[dict] | None = None) -> None:
        self._bars = bars or []

    def available(self) -> bool:
        return True

    def read_bars_window(self, *_args) -> list[dict]:
        return self._bars


class FakeConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def execute(self, *_args, **_kwargs) -> "FakeConnection":
        return self

    def fetchall(self) -> list[tuple]:
        return self._rows

    def close(self) -> None:
        return None


class FakeManager:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def get_connection(self, _name: str) -> FakeConnection:
        return FakeConnection(self._rows)


def _bars(*items: tuple[str, float, float]) -> list[dict]:
    return [
        {"mkt_timestamp": ts, "close": close, "volume": volume}
        for ts, close, volume in items
    ]


def test_bucket_grid_truncates_last_bucket():
    grid = svc.build_bucket_grid("09:30", "10:00", 15)
    assert grid == [(34200, 35100), (35100, 36000)]
    assert svc.build_bucket_grid("10:00", "10:05", 15) == [(36000, 36300)]


@pytest.mark.parametrize(
    "start,end,bucket",
    [("10:00", "10:00", 5), ("10:01", "10:00", 5), ("09:00", "10:00", 7)],
)
def test_bucket_grid_rejects_invalid_input(start, end, bucket):
    with pytest.raises(ValueError):
        svc.build_bucket_grid(start, end, bucket)


def test_aggregate_marks_gap_and_accumulates_volume():
    grid = svc.build_bucket_grid("09:30", "09:32", 1)
    points, interval_vwap, bar_count = svc.aggregate_bars(
        _bars(("09:30:10", 10.0, 100.0), ("09:30:50", 11.0, 300.0)), grid
    )
    assert bar_count == 2
    assert points[0].is_gap is False
    assert points[0].price == 11.0
    assert points[0].vwap == pytest.approx(10.75)
    assert points[0].cum_volume == 400.0
    assert points[1].is_gap is True
    assert points[1].price is None
    assert points[1].cum_volume == 400.0
    assert interval_vwap == pytest.approx(10.75)


def test_aggregate_ignores_zero_volume_for_vwap():
    grid = svc.build_bucket_grid("09:30", "09:31", 1)
    points, interval_vwap, _ = svc.aggregate_bars(
        _bars(("09:30:10", 10.0, 0.0), ("09:30:20", 12.0, 0.0)), grid
    )
    assert points[0].vwap == pytest.approx(11.0)
    assert interval_vwap is None  # 无量不产生区间 VWAP


def test_load_prefers_intraday_then_formal():
    intraday = svc.load_interval_series(
        "AAPL US Equity",
        "20260408",
        "09:30",
        "09:32",
        1,
        intraday_reader=FakeReader(_bars(("09:30:10", 10.0, 100.0))),
        connection_manager=FakeManager([]),
    )
    assert intraday.source == "intraday"
    assert intraday.bar_count == 1

    formal = svc.load_interval_series(
        "AAPL US Equity",
        "20260408",
        "09:30",
        "09:32",
        1,
        intraday_reader=FakeReader([]),
        connection_manager=FakeManager([("09:30:10", 10.0, 50.0)]),
    )
    assert formal.source == "formal"
    assert formal.total_volume == 50.0


def test_load_returns_none_source_when_no_bars():
    series = svc.load_interval_series(
        "AAPL US Equity",
        "20260408",
        "09:30",
        "09:32",
        1,
        intraday_reader=FakeReader([]),
        connection_manager=FakeManager([]),
    )
    assert series.source == "none"
    assert series.gap_buckets == len(series.points)


def _client(monkeypatch, series: svc.IntervalSeries) -> TestClient:
    monkeypatch.setattr(router_module, "load_interval_series", lambda *_a, **_k: series)
    app = FastAPI()
    app.include_router(router_module.router)
    return TestClient(app)


def test_endpoint_returns_series(monkeypatch):
    series = svc.load_interval_series(
        "AAPL US Equity",
        "20260408",
        "09:30",
        "09:32",
        1,
        intraday_reader=FakeReader(_bars(("09:30:10", 10.0, 100.0))),
        connection_manager=FakeManager([]),
    )
    response = _client(monkeypatch, series).get(
        "/api/execution/interval-series",
        params={
            "equ_ticker": "AAPL US Equity",
            "trade_date": "20260408",
            "start": "09:30",
            "end": "09:32",
            "bucket_minutes": 1,
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["source"] == "intraday"
    assert payload["points"][1]["is_gap"] is True


def test_endpoint_rejects_invalid_bucket(monkeypatch):
    series = svc.load_interval_series(
        "AAPL US Equity", "20260408", "09:30", "09:32", 1,
        intraday_reader=FakeReader([]), connection_manager=FakeManager([]),
    )
    response = _client(monkeypatch, series).get(
        "/api/execution/interval-series",
        params={
            "equ_ticker": "AAPL US Equity",
            "trade_date": "20260408",
            "start": "09:30",
            "end": "09:32",
            "bucket_minutes": 7,
        },
    )
    assert response.status_code == 422
