"""Regression tests for RouteEx/ModifyRouteEx request construction."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytestmark = pytest.mark.anyio

from schemas import ModifyRouteRequest, Order, Route, RouteOrderRequest
import services.bloomberg_adapter as bloomberg_adapter

from services.bloomberg_adapter import BloombergEMSXService


class FakeSequenceItem:
    def __init__(self, storage: list[tuple[str, object]]):
        self._storage = storage

    def setElement(self, name: str, value: object):
        self._storage.append((name, value))


class FakeSequenceElement:
    def __init__(self):
        self.values: list[tuple[str, object]] = []

    def appendElement(self) -> FakeSequenceItem:
        return FakeSequenceItem(self.values)


class FakeStrategyElement:
    def __init__(self):
        self.strategy_name = ""
        self.field_indicators = FakeSequenceElement()
        self.fields = FakeSequenceElement()

    def setElement(self, name: str, value: object):
        if name == "EMSX_STRATEGY_NAME":
            self.strategy_name = str(value)

    def getElement(self, name: str):
        if name == "EMSX_STRATEGY_FIELD_INDICATORS":
            return self.field_indicators
        if name == "EMSX_STRATEGY_FIELDS":
            return self.fields
        raise KeyError(name)


class FakeRequest:
    def __init__(self, name: str):
        self.name = name
        self.fields: dict[str, object] = {}
        self.strategy = FakeStrategyElement()

    def set(self, name: str, value: object):
        self.fields[name] = value

    def getElement(self, name: str):
        if name == "EMSX_STRATEGY_PARAMS":
            return self.strategy
        raise KeyError(name)


class FakeRequestService:
    def __init__(self):
        self.requests: list[FakeRequest] = []

    def createRequest(self, name: str) -> FakeRequest:
        request = FakeRequest(name)
        self.requests.append(request)
        return request


class FakeMessage:
    def __init__(self, elements: dict[str, object] | None = None):
        self._elements = elements or {}
        self._correlation_ids: list[object] = []

    def messageType(self):
        return "Response"

    def hasElement(self, name: str) -> bool:
        return name in self._elements

    def getElementAsInteger(self, name: str) -> int:
        return int(self._elements[name])

    def getElementAsString(self, name: str) -> str:
        return str(self._elements[name])

    def correlationIds(self):
        return self._correlation_ids


class FakeEvent:
    def __init__(self, event_type: int, messages: list[FakeMessage]):
        self._event_type = event_type
        self._messages = messages

    def eventType(self) -> int:
        return self._event_type

    def __iter__(self):
        return iter(self._messages)


class FakeRequestSession:
    def __init__(self):
        self._events: list[FakeEvent] = []

    def sendRequest(self, request, correlationId):
        other_cid = bloomberg_adapter.blpapi.CorrelationId("other")
        keep_partial = FakeMessage({"TOKEN": "keep-partial"})
        keep_partial._correlation_ids = [correlationId]
        ignore_partial = FakeMessage({"TOKEN": "ignore-partial"})
        ignore_partial._correlation_ids = [other_cid]
        keep_final = FakeMessage({"TOKEN": "keep-final"})
        keep_final._correlation_ids = [correlationId]
        ignore_final = FakeMessage({"TOKEN": "ignore-final"})
        ignore_final._correlation_ids = [other_cid]

        self._events = [
            FakeEvent(bloomberg_adapter.Event.PARTIAL_RESPONSE, [ignore_partial, keep_partial]),
            FakeEvent(bloomberg_adapter.Event.RESPONSE, [ignore_final, keep_final]),
        ]

    def nextEvent(self, timeout_ms):
        if self._events:
            return self._events.pop(0)
        return FakeEvent(bloomberg_adapter.Event.TIMEOUT, [])


def make_order() -> Order:
    return Order(
        id="1001",
        symbol="AAPL US Equity",
        side="BUY",
        status="WORKING",
        orderType="LIMIT",
        quantity=500,
        filledQuantity=0,
        remainingQuantity=500,
        price=123.45,
        stopPrice=None,
        timeInForce="DAY",
        account="ACC",
        portfolio="PF",
        trader="TRADER1",
        createdAt="2026-04-23T09:30:00",
        updatedAt="2026-04-23T09:30:00",
    )


def make_route(order_type: str = "LMT", limit_price: float | None = 123.45, stop_price: float | None = 95.0) -> Route:
    return Route(
        routeId=7,
        sequence=1001,
        id="1001.7",
        status="WORKING",
        broker="BMTB",
        amount=200,
        filled=0,
        working=200,
        remainBalance=200,
        avgPrice=None,
        limitPrice=limit_price,
        stopPrice=stop_price,
        orderType=order_type,
        tif="DAY",
    )


async def _connect_ok() -> bool:
    return True


async def test_route_order_maps_frontend_order_types_and_keeps_strategy_name():
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service._orders = {"1001": make_order()}
    service.connect = _connect_ok  # type: ignore[method-assign]
    service.get_terminal_trader_name = lambda: "TRADER1"  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage({"EMSX_ROUTE_ID": 42})]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    result = await service.route_order(
        RouteOrderRequest(
            orderId="1001",
            broker="BMTB",
            quantity=100,
            orderType="MARKET",
            price=123.45,
            timeInForce="DAY",
            strategyParams={"strategyName": "TWAP", "fields": []},
        )
    )

    request = fake_service.requests[0]
    assert request.name == "RouteEx"
    assert request.fields["EMSX_ORDER_TYPE"] == "MKT"
    assert "EMSX_LIMIT_PRICE" not in request.fields
    assert request.strategy.strategy_name == "TWAP"
    assert result["routeId"] == 42


async def test_modify_route_uses_reset_sentinels_for_explicit_null_prices():
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service._routes = {"1001.7": make_route(order_type="LMT", limit_price=123.45, stop_price=95.0)}
    service.connect = _connect_ok  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage()]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    ok = await service.modify_route(
        ModifyRouteRequest(
            sequence=1001,
            routeId=7,
            orderType="MARKET",
            limitPrice=None,
            stopPrice=None,
        )
    )

    request = fake_service.requests[0]
    assert ok is True
    assert request.name == "ModifyRouteEx"
    assert request.fields["EMSX_ORDER_TYPE"] == "MKT"
    assert request.fields["EMSX_LIMIT_PRICE"] == -99999
    assert request.fields["EMSX_STOP_PRICE"] == -1


async def test_modify_route_auto_resets_limit_when_switching_away_from_limit_type():
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service._routes = {"1001.7": make_route(order_type="LMT", limit_price=123.45, stop_price=None)}
    service.connect = _connect_ok  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage()]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    await service.modify_route(
        ModifyRouteRequest(
            sequence=1001,
            routeId=7,
            orderType="MARKET",
        )
    )

    request = fake_service.requests[0]
    assert request.fields["EMSX_ORDER_TYPE"] == "MKT"
    assert request.fields["EMSX_LIMIT_PRICE"] == -99999


async def test_modify_route_treats_empty_strategy_fields_as_skipped():
    """Bloomberg rejects FIELD_INDICATOR=0 combined with empty EMSX_FIELD_DATA
    with "Invalid Strategy Parameter". Empty enabled fields must be submitted
    as indicator=1 (skip) so that changing a single parameter (e.g. Max%Vol)
    does not fail because unrelated fields have no default value.
    """
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service._routes = {"1001.7": make_route(order_type="LMT", limit_price=10.0, stop_price=None)}
    service.connect = _connect_ok  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage()]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    await service.modify_route(
        ModifyRouteRequest(
            sequence=1001,
            routeId=7,
            strategyParams={
                "strategyName": "VWAP",
                "fields": [
                    {"value": "09:30:00", "disabled": False},  # StartTime
                    {"value": "", "disabled": False},            # EndTime (empty, should be skipped)
                    {"value": "8", "disabled": False},           # Max%Vol
                    {"value": None, "disabled": False},          # None treated as empty → skip
                    {"value": "foo", "disabled": True},          # Explicitly disabled
                ],
            },
        )
    )

    request = fake_service.requests[0]
    data_values = [value for _, value in request.strategy.fields.values]
    indicator_values = [value for _, value in request.strategy.field_indicators.values]
    assert request.strategy.strategy_name == "VWAP"
    assert data_values == ["09:30:00", "", "8", "", ""]
    assert indicator_values == [0, 1, 0, 1, 1]


async def test_get_asset_class_uses_request_response_value():
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service.connect = _connect_ok  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage({"EMSX_ASSET_CLASS": "FUT"})]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    asset_class = await service.get_asset_class("ESM6 Index")

    request = fake_service.requests[0]
    assert request.name == "GetAssetClass"
    assert request.fields["EMSX_TICKER"] == "ESM6 Index"
    assert asset_class == "FUT"


async def test_get_asset_class_defaults_to_eqty_when_response_missing():
    service = BloombergEMSXService()
    fake_service = FakeRequestService()
    service.connected = True
    service._request_service = fake_service
    service.connect = _connect_ok  # type: ignore[method-assign]

    async def fake_send_request(request):
        return [FakeMessage()]

    service._send_request_async = fake_send_request  # type: ignore[method-assign]

    asset_class = await service.get_asset_class("IBM US Equity")

    assert fake_service.requests[0].name == "GetAssetClass"
    assert asset_class == "EQTY"


def test_send_request_filters_messages_by_correlation_id():
    service = BloombergEMSXService()
    service.connected = True
    service._request_session = FakeRequestSession()
    bloomberg_adapter.settings = SimpleNamespace(BLOOMBERG_TIMEOUT=1000)

    messages = service._send_request(FakeRequest("GetBrokersWithAssetClass"))

    assert [msg.getElementAsString("TOKEN") for msg in messages] == ["keep-partial", "keep-final"]


def test_track_api_seq_num_warns_on_gap(monkeypatch):
    service = BloombergEMSXService()
    warnings: list[str] = []

    monkeypatch.setattr(bloomberg_adapter.logger, "warning", lambda message: warnings.append(message))

    service._track_api_seq_num(FakeMessage({"API_SEQ_NUM": 1}), "order")
    service._track_api_seq_num(FakeMessage({"API_SEQ_NUM": 3}), "order")

    assert service._last_order_api_seq_num == 3
    assert any("ORDER API_SEQ_NUM gap detected" in message for message in warnings)


def test_get_startup_status_infers_ready_from_populated_caches():
    service = BloombergEMSXService()
    service.connected = True
    service.connection_time = datetime.now() - timedelta(seconds=5)
    service._orders = {"1001": make_order()}
    service._routes = {"1001.7": make_route()}
    service._init_paint_done = False
    service._route_init_paint_done = False

    status = service.get_startup_status()

    assert status.phase == "ready"
    assert status.ready is True
    assert status.subscriptions.ordersInitPaintDone is True
    assert status.subscriptions.routesInitPaintDone is True