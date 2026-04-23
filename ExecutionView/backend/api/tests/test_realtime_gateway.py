"""Tests for RealtimeGateway: fanout, cursor replay, disconnect cleanup."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

# Import under test
from services.realtime_gateway import RealtimeGateway
from services.event_serializers import order_delta, route_delta, make_event


# ---------------------------------------------------------------------------
# event_serializers tests
# ---------------------------------------------------------------------------

class TestEventSerializers:
    def test_make_event_structure(self):
        evt = make_event(event_type="update", entity="order", key="123", data={"id": "123"}, version=1)
        assert evt["type"] == "update"
        assert evt["entity"] == "order"
        assert evt["key"] == "123"
        assert evt["version"] == 1
        assert "ts" in evt
        assert evt["data"] == {"id": "123"}

    def test_order_delta(self):
        evt = order_delta("snapshot", {"id": "42", "symbol": "AAPL"})
        assert evt["entity"] == "order"
        assert evt["key"] == "42"
        assert evt["data"]["symbol"] == "AAPL"

    def test_route_delta(self):
        evt = route_delta("update", {"id": "42.1", "sequence": 42, "broker": "GS"})
        assert evt["entity"] == "route"
        assert evt["key"] == "42.1"
        assert evt["version"] == 42


# ---------------------------------------------------------------------------
# RealtimeGateway tests
# ---------------------------------------------------------------------------

def _mock_ws(*, fail_send=False):
    ws = AsyncMock()
    ws.accept = AsyncMock()
    if fail_send:
        ws.send_text = AsyncMock(side_effect=Exception("closed"))
    else:
        ws.send_text = AsyncMock()
    return ws


class TestRealtimeGateway:
    @pytest.fixture
    def gw(self):
        return RealtimeGateway(buffer_size=100)

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, gw):
        ws = _mock_ws()
        await gw.connect(ws)
        assert gw.client_count == 1
        gw.disconnect(ws)
        assert gw.client_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_order(self, gw):
        ws = _mock_ws()
        await gw.connect(ws)
        await gw.broadcast_order({"id": "1", "symbol": "AAPL"}, event_type="update")
        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["entity"] == "order"
        assert payload["cursor"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_route(self, gw):
        ws = _mock_ws()
        await gw.connect(ws)
        await gw.broadcast_route({"id": "1.1", "sequence": 1, "broker": "MS"}, event_type="update")
        ws.send_text.assert_called_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["entity"] == "route"

    @pytest.mark.asyncio
    async def test_dead_client_cleanup(self, gw):
        good = _mock_ws()
        bad = _mock_ws(fail_send=True)
        await gw.connect(good)
        await gw.connect(bad)
        assert gw.client_count == 2
        await gw.broadcast_order({"id": "1"}, event_type="update")
        assert gw.client_count == 1  # bad client removed
        good.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cursor_replay(self, gw):
        ws = _mock_ws()
        await gw.connect(ws)
        # Publish 5 events
        for i in range(5):
            await gw.broadcast_order({"id": str(i)}, event_type="update")
        assert gw.latest_cursor == 5

        # Replay from cursor 3 (should get events 4 and 5)
        replay_ws = _mock_ws()
        count = await gw.replay_since(replay_ws, 3)
        assert count == 2

    @pytest.mark.asyncio
    async def test_buffer_overflow(self):
        gw = RealtimeGateway(buffer_size=5)
        for i in range(10):
            await gw.broadcast_order({"id": str(i)}, event_type="update")
        assert gw.latest_cursor == 10
        assert len(gw._buffer) == 5  # only last 5 kept

    @pytest.mark.asyncio
    async def test_stats(self, gw):
        ws = _mock_ws()
        await gw.connect(ws)
        await gw.broadcast_order({"id": "1"}, event_type="update")
        s = gw.stats()
        assert s["connected_clients"] == 1
        assert s["latest_cursor"] == 1
        assert s["buffer_size"] == 1

    @pytest.mark.asyncio
    async def test_no_clients_still_buffers(self, gw):
        await gw.broadcast_order({"id": "1"}, event_type="update")
        assert gw.latest_cursor == 1
        assert len(gw._buffer) == 1
