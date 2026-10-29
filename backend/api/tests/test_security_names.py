"""证券中文简称端点：解析、缓存边界与接口契约（MarketView Name 列的数据源）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from routers import securities  # noqa: E402
from services.bloomberg import security_names as sn  # noqa: E402


# ── blpapi 消息替身（只为覆盖 ReferenceDataResponse 的取值结构）──────────────
class _Element:
    def __init__(self, value, present: bool = True, null: bool = False):
        self._value = value
        self._present = present
        self._null = null

    def isNull(self) -> bool:
        return self._null or self._value is None

    def getValueAsString(self) -> str:
        return str(self._value)


class _FieldData:
    def __init__(self, fields: dict):
        self._fields = fields

    def hasElement(self, name: str) -> bool:
        return name in self._fields

    def getElement(self, name: str):
        return self._fields[name]


class _Item:
    def __init__(self, ticker: str, name=None, error: bool = False):
        self._ticker = ticker
        self._error = error
        self._data = {"security": _Element(ticker)}
        if name is not None:
            self._data["fieldData"] = _FieldData({sn.FIELD: _Element(name)})

    def hasElement(self, name: str) -> bool:
        return name in self._data or (name == "securityError" and self._error)

    def getElementAsString(self, name: str) -> str:
        return self._data[name].getValueAsString()

    def getElement(self, name: str):
        return self._data[name]


class _SecurityData:
    def __init__(self, items: list):
        self._items = items

    def numValues(self) -> int:
        return len(self._items)

    def getValueAsElement(self, index: int):
        return self._items[index]


class _Message:
    def __init__(self, items: list):
        self._items = items

    def hasElement(self, name: str) -> bool:
        return name == "securityData"

    def getElement(self, name: str):
        return _SecurityData(self._items) if name == "securityData" else None


# ── 解析 ──────────────────────────────────────────────────────────────────
def test_extract_names_keeps_only_resolved_values():
    message = _Message([
        _Item("AAPL US Equity", "苹果公司"),
        _Item("700 HK Equity", "腾讯控股有限公司"),
        _Item("BAD US Equity", error=True),
        _Item("NULL US Equity"),
        _Item("EMPTY US Equity", "   "),
    ])

    names = sn.extract_names(message)

    assert names == {"AAPL US Equity": "苹果公司", "700 HK Equity": "腾讯控股有限公司"}


def test_extract_names_ignores_messages_without_security_data():
    class _Empty:
        def hasElement(self, name: str) -> bool:
            return False

    assert sn.extract_names(_Empty()) == {}


# ── 缓存 ──────────────────────────────────────────────────────────────────
def test_service_caches_hits_and_reports_missing(monkeypatch):
    service = sn.SecurityNamesService()
    calls: list[list[str]] = []

    def fake_fetch(tickers, field=sn.DEFAULT_FIELD):
        calls.append(list(tickers))
        service._cache.update(
            {(field, ticker): f"名称-{ticker}" for ticker in tickers[:1]}
        )

    monkeypatch.setattr(service, "_fetch", fake_fetch)

    names, missing = service.get_names(["A", "B", "A"])
    assert names == {"A": "名称-A"}
    assert missing == ["B"]

    # 第二次：A 命中缓存，只请求 B
    service.get_names(["A", "B"])
    assert calls == [["A", "B"], ["B"]]


def test_service_keeps_fields_in_separate_cache_entries(monkeypatch):
    service = sn.SecurityNamesService()

    def fake_fetch(tickers, field=sn.DEFAULT_FIELD):
        service._cache.update({(field, ticker): f"{field}-{ticker}" for ticker in tickers})

    monkeypatch.setattr(service, "_fetch", fake_fetch)

    zh, _ = service.get_names(["A"], sn.DEFAULT_FIELD)
    short, _ = service.get_names(["A"], "SHORT_NAME")
    assert zh == {"A": f"{sn.DEFAULT_FIELD}-A"}
    assert short == {"A": "SHORT_NAME-A"}


def test_service_survives_terminal_failure(monkeypatch):
    service = sn.SecurityNamesService()

    def boom(tickers, field=sn.DEFAULT_FIELD):
        raise RuntimeError("blpapi down")

    monkeypatch.setattr(service, "_fetch", boom)

    names, missing = service.get_names(["A"])
    assert names == {}
    assert missing == ["A"]


# ── 端点 ──────────────────────────────────────────────────────────────────
def _client(monkeypatch, resolver=None) -> TestClient:
    app = FastAPI()
    app.include_router(securities.router)
    if resolver is not None:
        monkeypatch.setattr(securities._name_service, "get_names", resolver)
    return TestClient(app)


def test_endpoint_returns_names_and_missing(monkeypatch):
    client = _client(
        monkeypatch,
        lambda tickers, field=sn.DEFAULT_FIELD: ({"AAPL US Equity": "苹果公司"}, ["BAD US Equity"]),
    )

    response = client.get("/api/securities/names?tickers=AAPL%20US%20Equity,BAD%20US%20Equity")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["names"] == {"AAPL US Equity": "苹果公司"}
    assert data["missing"] == ["BAD US Equity"]
    assert data["field"] == "NAME_CHINESE_SIMPLIFIED"


def test_endpoint_accepts_short_name_field(monkeypatch):
    seen: list[str] = []

    def resolver(tickers, field=sn.DEFAULT_FIELD):
        seen.append(field)
        return {"AAPL US Equity": "APPLE INC"}, []

    client = _client(monkeypatch, resolver)
    response = client.get("/api/securities/names?tickers=AAPL%20US%20Equity&field=SHORT_NAME")

    assert response.status_code == 200
    assert response.json()["data"]["field"] == "SHORT_NAME"
    assert seen == ["SHORT_NAME"]


def test_endpoint_rejects_unknown_field(monkeypatch):
    client = _client(monkeypatch, lambda tickers, field=sn.DEFAULT_FIELD: ({}, []))
    response = client.get("/api/securities/names?tickers=AAPL%20US%20Equity&field=SECURITY_DES")
    assert response.status_code == 400


def test_endpoint_rejects_empty_and_oversized_lists(monkeypatch):
    client = _client(monkeypatch, lambda tickers: ({}, []))

    assert client.get("/api/securities/names?tickers=,,,").status_code == 400
    oversized = ",".join(f"T{i} US Equity" for i in range(securities.MAX_TICKERS + 1))
    assert client.get(f"/api/securities/names?tickers={oversized}").status_code == 400
