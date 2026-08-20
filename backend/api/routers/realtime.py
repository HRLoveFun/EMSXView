"""Realtime router — /ws/orders WebSocket endpoint."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from services.auth_service import authenticate as _authenticate
from services.realtime_gateway import realtime_gw

logger = logging.getLogger("main")

router = APIRouter()


@router.websocket("/ws/orders")
async def websocket_endpoint(websocket: WebSocket, token: str | None = None):
    """WebSocket endpoint for real-time order/route updates.

    防护 (H3): 浏览器 WebSocket API 无法携带自定义 header,
    认证 token 通过 query 参数传入, 无效时拒绝握手 (code 4401)。
    开发模式 BYPASS_AUTH=true 时行为不变。

    Supports: ping/pong, cursor-based backfill, stats.
    """
    try:
        _authenticate(token)
    except HTTPException:
        logger.warning("Realtime WS 未认证连接被拒绝")
        await websocket.close(code=4401, reason="Unauthorized")
        return

    await realtime_gw.connect(websocket)
    try:
        await websocket.send_json({
            "type": "connected",
            "cursor": realtime_gw.latest_cursor,
            "timestamp": datetime.now().isoformat(),
        })
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            action = message.get("action", "")
            if action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            elif action == "replay":
                since = int(message.get("cursor", 0))
                count = await realtime_gw.replay_since(websocket, since)
                await websocket.send_json({
                    "type": "replay_done",
                    "replayed": count,
                    "cursor": realtime_gw.latest_cursor,
                })
            elif action == "stats":
                await websocket.send_json({"type": "stats", **realtime_gw.stats()})
    except WebSocketDisconnect:
        realtime_gw.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        realtime_gw.disconnect(websocket)
