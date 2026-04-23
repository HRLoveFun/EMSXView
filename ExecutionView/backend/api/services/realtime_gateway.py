"""
Realtime gateway — manages WebSocket connections, broadcasts deltas,
and supports cursor-based backfill on reconnect.

Usage from main.py::

    from services.realtime_gateway import realtime_gw
    # After an order update:
    await realtime_gw.broadcast_order(order.model_dump(), event_type="update")
    # After a route update:
    await realtime_gw.broadcast_route(route.model_dump(), event_type="update")
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from typing import Any, Literal

from fastapi import WebSocket

from services.event_serializers import order_delta, route_delta

logger = logging.getLogger(__name__)

# Ring-buffer size for cursor replay (keep last N events)
_DEFAULT_BUFFER_SIZE = 2000


class RealtimeGateway:
    """Connection registry + delta broadcaster + cursor replay buffer."""

    def __init__(self, buffer_size: int = _DEFAULT_BUFFER_SIZE):
        self._connections: list[WebSocket] = []
        # Ring buffer: each entry is (cursor, event_dict)
        self._buffer: collections.deque[tuple[int, dict[str, Any]]] = collections.deque(
            maxlen=buffer_size,
        )
        self._cursor: int = 0  # monotonic event counter
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("Realtime client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("Realtime client disconnected (%d total)", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast_order(
        self,
        order_dict: dict[str, Any],
        event_type: Literal["snapshot", "update", "delete"] = "update",
    ) -> None:
        event = order_delta(event_type, order_dict)
        await self._publish(event)

    async def broadcast_route(
        self,
        route_dict: dict[str, Any],
        event_type: Literal["snapshot", "update", "delete"] = "update",
    ) -> None:
        event = route_delta(event_type, route_dict)
        await self._publish(event)

    async def _publish(self, event: dict[str, Any]) -> None:
        """Append to buffer and fan-out to all connected clients."""
        async with self._lock:
            self._cursor += 1
            event["cursor"] = self._cursor
            self._buffer.append((self._cursor, event))

        if not self._connections:
            return

        payload = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    # ------------------------------------------------------------------
    # Cursor-based backfill
    # ------------------------------------------------------------------

    async def replay_since(self, ws: WebSocket, since_cursor: int) -> int:
        """Send all buffered events with cursor > since_cursor. Return count sent."""
        count = 0
        for cursor, event in self._buffer:
            if cursor > since_cursor:
                try:
                    await ws.send_text(json.dumps(event))
                    count += 1
                except Exception:
                    break
        return count

    @property
    def latest_cursor(self) -> int:
        return self._cursor

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "connected_clients": len(self._connections),
            "buffer_size": len(self._buffer),
            "latest_cursor": self._cursor,
        }


# Module-level singleton
realtime_gw = RealtimeGateway()
