"""盘中市场状态端点（057 DL-15；`EMSXVIEW_INTRADAY_STATE_ENABLED` 默认开启）。

- REST `GET /api/market-state/snapshot`：一次性快照（关闭时返回 `enabled:false`）；
- WS `/ws/market-state`：连接后按 `EMSXVIEW_MARKET_STATE_PUSH_INTERVAL`（默认 5s）
  推送一次快照事件。
- 两者都接受 `tickers` 白名单，避免把全量订单标的推给 MarketView 股票池。
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from config import settings
from deps import get_bloomberg_service, verify_token
from schemas import ApiResponse
from services import market_state_service as mss
from services.realtime_gateway import realtime_gw

router = APIRouter(tags=["MarketState"])

#: 单次请求/单条 WS 连接的 ticker 白名单上限（与 /subscribe 的 max_length 对齐）
MAX_TICKERS = 500
#: REST 与 WS 共用的 tickers 说明
TICKERS_QUERY = (
    "逗号分隔的 ticker 白名单（如 `AAPL US Equity,MSFT US Equity`）；"
    f"缺省返回全部订阅标的，上限 {MAX_TICKERS} 个"
)


def _baseline_lookup(tickers: list) -> dict:
    """日度基线查询（DL-10 适配器；失败由服务层降级为无基线比较）。"""
    from platform_data.adapters import DailyBaselineAdapter

    return {baseline.equ_ticker: baseline for baseline in DailyBaselineAdapter().get_baseline(tickers)}


def parse_tickers(raw: str | None) -> list[str] | None:
    """解析逗号分隔的 ticker 白名单；空值返回 None（不过滤）。"""
    if not raw:
        return None
    items = [part.strip() for part in raw.split(",") if part.strip()]
    if not items:
        return None
    if len(items) > MAX_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tickers ({len(items)}); max {MAX_TICKERS} per request",
        )
    return items


@router.get("/api/market-state/snapshot", response_model=ApiResponse)
async def get_market_state_snapshot(
    tickers: str | None = Query(default=None, description=TICKERS_QUERY),
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """逐票盘中状态快照（开关关闭时返回 `enabled:false`，不报错）。

    `tickers` 可选：MarketView 股票池工作站只取池内标的，避免把全量订单标的推给前端。
    """
    if not mss.intraday_state_enabled():
        return ApiResponse(
            success=True,
            data={"enabled": False, "tickers": []},
            message="intraday market state disabled (EMSXVIEW_INTRADAY_STATE_ENABLED)",
        )
    snapshot = await asyncio.to_thread(
        mss.build_market_state_snapshot,
        bloomberg,
        baseline_lookup=_baseline_lookup,
        tickers=parse_tickers(tickers),
    )
    return ApiResponse(success=True, data=mss.snapshot_payload(snapshot))


class SubscribeRequest(BaseModel):
    tickers: list[str] = Field(default_factory=list, max_length=500)


@router.post("/api/market-state/subscribe", response_model=ApiResponse)
async def subscribe_market_state(
    request: SubscribeRequest,
    user: dict = Depends(verify_token),
    bloomberg=Depends(get_bloomberg_service),
) -> ApiResponse:
    """注册额外 mktdata 订阅标的（057 DL-29：池内标的实时价）。

    订阅由 core 后端发起；MarketView/前端只提交 ticker 列表，不直连 Bloomberg。
    """
    if not mss.intraday_state_enabled():
        return ApiResponse(
            success=True,
            data={"accepted": [], "rejected": 0, "total_extra": 0},
            message="intraday market state disabled (EMSXVIEW_INTRADAY_STATE_ENABLED)",
        )
    accepted, rejected, total = bloomberg.add_mktdata_tickers(request.tickers)
    return ApiResponse(
        success=True,
        data={"accepted": sorted(accepted), "rejected": rejected, "total_extra": total},
        message=f"subscribed {len(accepted)} extra ticker(s)",
    )


@router.get("/api/market-state/thresholds", response_model=ApiResponse)
async def get_monitor_thresholds(user: dict = Depends(verify_token)) -> ApiResponse:
    """MonitorBoard 服务端默认阈值（版本化；用户本地自定义优先于本默认）。"""
    return ApiResponse(success=True, data=mss.monitor_thresholds())


@router.websocket("/ws/market-state")
async def ws_market_state(
    ws: WebSocket,
    tickers: str | None = Query(default=None, description=TICKERS_QUERY),
):
    """每 5 秒推送一次快照；开关关闭时推送 `enabled:false` 心跳。

    `tickers` 与 REST 同义：连接期固定白名单（前端切换股票池时以新 URL 重连），
    服务端按白名单裁剪推送内容并跳过无关标的的基线查询。白名单超限直接拒绝
    握手，不降级成「推送全部标的」。
    """
    try:
        wanted = parse_tickers(tickers)
    except HTTPException:
        await ws.close(code=1008)
        return
    await realtime_gw.connect(ws)
    try:
        while True:
            if mss.intraday_state_enabled():
                bloomberg = ws.app.state.bloomberg_service
                snapshot = await asyncio.to_thread(
                    mss.build_market_state_snapshot,
                    bloomberg,
                    baseline_lookup=_baseline_lookup,
                    tickers=wanted,
                )
                await ws.send_text(json.dumps({"type": "market_state", "data": mss.snapshot_payload(snapshot)}))
            else:
                await ws.send_text(
                    json.dumps({"type": "market_state", "data": {"enabled": False, "tickers": []}})
                )
            await asyncio.sleep(max(0.05, float(settings.EMSXVIEW_MARKET_STATE_PUSH_INTERVAL)))
    except (WebSocketDisconnect, RuntimeError):
        realtime_gw.disconnect(ws)
    except Exception:
        realtime_gw.disconnect(ws)
        raise
